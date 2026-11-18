"""Feedback persistence, SMTP failure recovery and concurrent outbox delivery."""

import json
import smtplib
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from feedback import FeedbackHandler, FeedbackServer, store_feedback
from feedback_mail import deliver_next, send_notification


class MailTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / 'feedback.sqlite3'

    def query(self, sql):
        with sqlite3.connect(str(self.database)) as connection:
            return connection.execute(sql).fetchall()

    def test_existing_feedback_is_not_queued(self):
        store_feedback(self.database, 'Historical feedback')
        store_feedback(self.database, 'New feedback', notify=True)
        self.assertEqual(self.query('SELECT feedback_id FROM feedback_mail'), [(2,)])
        self.assertEqual(len(self.query('SELECT * FROM feedback')), 2)

    def test_submit_then_retry_without_losing_feedback(self):
        server = FeedbackServer(('127.0.0.1', 0), FeedbackHandler)
        server.feedback_database = self.database
        server.feedback_mail_enabled = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request('http://127.0.0.1:%d/api/feedback' % server.server_port,
                              data=json.dumps({'message': '测试意见'}).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 201)
                self.assertEqual(json.load(response), {'result': 'saved'})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        with patch('feedback_mail.send_notification', side_effect=smtplib.SMTPException('test')):
            self.assertTrue(deliver_next(self.database, {}))
        self.assertEqual(self.query('SELECT message FROM feedback'), [('测试意见',)])
        self.assertEqual(self.query('SELECT attempts, sent_at FROM feedback_mail'), [(1, None)])
        with patch('feedback_mail.send_notification') as sender:
            self.assertFalse(deliver_next(self.database, {}))
            sender.assert_not_called()
        with sqlite3.connect(str(self.database)) as connection:
            connection.execute('UPDATE feedback_mail SET next_attempt=0')
        # Each invocation opens the persisted database as a restarted worker would.
        with patch('feedback_mail.send_notification') as sender:
            self.assertTrue(deliver_next(self.database, {}))
            sender.assert_called_once()
            self.assertFalse(deliver_next(self.database, {}))
        self.assertEqual(self.query('SELECT attempts, sent_at IS NOT NULL FROM feedback_mail'), [(2, 1)])

    def test_workers_claim_feedback_once(self):
        store_feedback(self.database, 'Concurrent delivery', notify=True)
        with patch('feedback_mail.send_notification') as sender:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: deliver_next(self.database, {}), range(2)))
            self.assertEqual(sorted(results), [False, True])
            sender.assert_called_once()

    def test_smtp_message_uses_tls_and_configured_recipient(self):
        config = dict(host='smtp.example.com', port=465, security='ssl', username='test',
                      password='test', sender='sender@example.com', recipient='owner@example.com')
        with patch('feedback_mail.smtplib.SMTP_SSL') as smtp:
            send_notification(config, (3, '2026-11-18T02:00:00+00:00', '中文反馈'))
            smtp.assert_called_once()
            client = smtp.return_value
            mail = client.send_message.call_args[0][0]
            self.assertEqual(mail['To'], 'owner@example.com')
            self.assertIn('中文反馈', mail.get_content())
            client.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
