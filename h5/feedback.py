"""Loopback-only feedback API and owner-only inbox command."""

import argparse
import json
import re
import sqlite3
import threading
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

from feedback_mail import initialize_outbox, load_config, run_mail_worker
from feedback_region import lookup_region


MAX_MESSAGE = 2000
MAX_BODY = 12 * 1024


def initialize_feedback(connection):
    connection.execute(
        'CREATE TABLE IF NOT EXISTS feedback '
        '(id INTEGER PRIMARY KEY, submitted_at TEXT NOT NULL, message TEXT NOT NULL, source_region TEXT)'
    )


def prepare_database(database, notify=False):
    with closing(sqlite3.connect(str(database))) as connection:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            initialize_feedback(connection)
            columns = {column[1] for column in connection.execute('PRAGMA table_info(feedback)')}
            if 'source_region' not in columns:
                connection.execute('ALTER TABLE feedback ADD COLUMN source_region TEXT')
            if notify:
                initialize_outbox(connection)


def store_feedback(database, message, notify=False, source_region=None):
    with closing(sqlite3.connect(str(database))) as connection:
        with connection:
            initialize_feedback(connection)
            cursor = connection.execute(
                'INSERT INTO feedback (submitted_at, message, source_region) VALUES (?, ?, ?)',
                (datetime.now(timezone.utc).isoformat(timespec='seconds'), message, source_region),
            )
            if notify:
                initialize_outbox(connection)
                connection.execute('INSERT INTO feedback_mail (feedback_id) VALUES (?)', (cursor.lastrowid,))


def show_inbox(database):
    if not database.is_file():
        print('暂无反馈。')
        return
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute('SELECT * FROM feedback ORDER BY id DESC'):
            feedback = dict(row)
            feedback.setdefault('source_region', None)
            print(json.dumps(feedback, ensure_ascii=False))


class FeedbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/api/feedback':
            return self.send_error(404)
        database = getattr(self.server, 'feedback_database', None)
        if database is None:
            return self.reply(503, 'feedback_unavailable')
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, 'json_required')
        length = self.headers.get('Content-Length', '')
        if not re.fullmatch(r'[0-9]{1,9}', length):
            return self.reply(400, 'invalid_body')
        if int(length) > MAX_BODY:
            return self.reply(413, 'too_long')
        try:
            raw = self.rfile.read(int(length))
            if len(raw) != int(length):
                return self.reply(400, 'invalid_body')
            data = json.loads(raw.decode('utf-8'))
            message = data.get('message') if isinstance(data, dict) else None
            if not isinstance(message, str):
                return self.reply(400, 'invalid_message')
            message = message.strip()
            message.encode('utf-8')
        except (ValueError, OSError):
            return self.reply(400, 'invalid_body')
        if not message or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', message):
            return self.reply(400, 'invalid_message')
        if len(message) > MAX_MESSAGE:
            return self.reply(413, 'too_long')
        try:
            store_feedback(database, message, getattr(self.server, 'feedback_mail_enabled', False),
                           self.source_region())
        except sqlite3.Error as error:
            self.log_error('Feedback storage failed: %s', type(error).__name__)
            return self.reply(503, 'feedback_unavailable')
        return self.reply(201, 'saved')

    def source_region(self):
        reader = getattr(self.server, 'feedback_region_reader', None)
        if reader is None or self.client_address[0] != '127.0.0.1':
            return None
        # Nginx must replace this header with its own connection's remote address.
        addresses = self.headers.get_all('X-Real-IP', [])
        if len(addresses) != 1:
            return None
        try:
            return lookup_region(reader, addresses[0].strip())
        except (ValueError, OSError, RuntimeError) as error:
            self.log_error('Feedback region lookup failed: %s', type(error).__name__)
            return None

    def reply(self, status, result):
        body = json.dumps({'result': result}).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FeedbackServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8781)
    parser.add_argument('--mail-config', type=Path, help='Private JSON file containing SMTP settings')
    parser.add_argument('--geoip-db', type=Path, help='Offline city MMDB used behind a trusted reverse proxy')
    parser.add_argument('--list', action='store_true', help='Read the inbox from the local database')
    args = parser.parse_args()
    if args.list:
        show_inbox(args.database)
        return
    mail_config = load_config(args.mail_config) if args.mail_config else None
    stop = threading.Event()
    with ExitStack() as resources:
        server = resources.enter_context(FeedbackServer(('127.0.0.1', args.port), FeedbackHandler))
        server.feedback_database = args.database
        server.feedback_mail_enabled = mail_config is not None
        if args.geoip_db:
            import maxminddb

            server.feedback_region_reader = resources.enter_context(
                closing(maxminddb.open_database(str(args.geoip_db), maxminddb.MODE_MMAP)))
        prepare_database(args.database, notify=server.feedback_mail_enabled)
        if mail_config:
            worker = threading.Thread(target=run_mail_worker, args=(args.database, mail_config, stop), daemon=True)
            worker.start()
        try:
            server.serve_forever()
        finally:
            stop.set()


if __name__ == '__main__':
    main()
