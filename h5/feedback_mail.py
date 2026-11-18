"""Durable SMTP notifications for newly submitted feedback (Python 3.6+)."""

import json
import logging
import smtplib
import sqlite3
import ssl
import time
from contextlib import closing
from email.message import EmailMessage
from email.utils import formatdate, parseaddr


def initialize_outbox(connection):
    connection.execute(
        'CREATE TABLE IF NOT EXISTS feedback_mail '
        '(feedback_id INTEGER PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, '
        'next_attempt REAL NOT NULL DEFAULT 0, sent_at REAL, last_error TEXT)'
    )


def load_config(path):
    with path.open(encoding='utf-8') as source:
        config = json.load(source)
    for key in ('host', 'username', 'password', 'sender', 'recipient'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError('Missing mail setting: ' + key)
    for key in ('sender', 'recipient'):
        address = config[key]
        if '\r' in address or '\n' in address or parseaddr(address)[1] != address or '@' not in address:
            raise ValueError('Invalid mail address: ' + key)
    config.setdefault('security', 'ssl')
    config.setdefault('port', 465 if config['security'] == 'ssl' else 587)
    if config['security'] not in ('ssl', 'starttls'):
        raise ValueError('Mail security must be ssl or starttls')
    if not isinstance(config['port'], int) or not 1 <= config['port'] <= 65535:
        raise ValueError('Invalid mail port')
    return config


def send_notification(config, feedback):
    feedback_id, submitted_at, text, source_region = feedback
    mail = EmailMessage()
    mail['From'] = config['sender']
    mail['To'] = config['recipient']
    mail['Subject'] = '动态乐谱拼接工具 · 新反馈 #{}'.format(feedback_id)
    mail['Date'] = formatdate(localtime=False)
    # Reuse the ID on retries so mail clients can recognize duplicates.
    mail['Message-ID'] = '<score-feedback-{}-{}@{}>'.format(
        feedback_id, submitted_at.replace(':', '').replace('+', ''),
        config['sender'].rsplit('@', 1)[1],
    )
    mail.set_content('收到一条网站反馈。\n\n编号：{}\n提交时间（UTC）：{}\n来源地区（IP 推测）：{}\n\n{}\n'.format(
        feedback_id, submitted_at, source_region or '未知', text))
    context = ssl.create_default_context()
    if config['security'] == 'ssl':
        client = smtplib.SMTP_SSL(config['host'], config['port'], timeout=20, context=context)
    else:
        client = smtplib.SMTP(config['host'], config['port'], timeout=20)
    try:
        if config['security'] == 'starttls':
            client.starttls(context=context)
        client.login(config['username'], config['password'])
        client.send_message(mail)
    finally:
        client.close()


def deliver_next(database, config):
    now = time.time()
    with closing(sqlite3.connect(str(database), timeout=10)) as connection:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT f.id, f.submitted_at, f.message, f.source_region, m.attempts '
                'FROM feedback_mail m JOIN feedback f ON f.id = m.feedback_id '
                'WHERE m.sent_at IS NULL AND m.next_attempt <= ? '
                'ORDER BY m.feedback_id LIMIT 1', (now,),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                'UPDATE feedback_mail SET attempts=attempts+1, next_attempt=? WHERE feedback_id=?',
                (now + 300, row[0]),
            )
        try:
            send_notification(config, row[:4])
        except (OSError, smtplib.SMTPException, ValueError) as error:
            # SMTP responses may contain personal data. Store only the error class.
            error_name = type(error).__name__
            delay = min(3600, 30 * 2 ** min(row[4], 7))
            with connection:
                connection.execute(
                    'UPDATE feedback_mail SET next_attempt=?, last_error=? WHERE feedback_id=?',
                    (time.time() + delay, error_name, row[0]),
                )
            logging.warning('Feedback mail #%s deferred (%s)', row[0], error_name)
        else:
            with connection:
                connection.execute(
                    'UPDATE feedback_mail SET sent_at=?, last_error=NULL WHERE feedback_id=?',
                    (time.time(), row[0]),
                )
            logging.info('Feedback mail #%s accepted by SMTP server', row[0])
    return True


def run_mail_worker(database, config, stop):
    while not stop.is_set():
        try:
            delivered = deliver_next(database, config)
        except sqlite3.Error as error:
            logging.warning('Feedback mail database unavailable (%s)', type(error).__name__)
            delivered = False
        stop.wait(1 if delivered else 5)
