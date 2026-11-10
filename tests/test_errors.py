import contextlib
import io
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from sources import describe_error


class ErrorTests(unittest.TestCase):
    def test_job_reports_http_refusal_without_private_details(self):
        job = {'id': 'test', 'cancel': threading.Event()}
        def rejected():
            raise urllib.error.HTTPError('https://example.test/?signature=private-value',
                                         412, 'Precondition Failed', {}, None)
        with contextlib.redirect_stdout(io.StringIO()):
            app.run(job, rejected)
        self.assertEqual(job['state'], 'error')
        self.assertIn('HTTP 412', job['message'])
        self.assertIn('本地视频', job['message'])
        self.assertNotIn('FFmpeg', job['message'])
        self.assertNotIn('private-value', job['message'])
        self.assertNotIn('example.test', job['message'])

    def test_network_causes_are_distinguished(self):
        for cause, expected in ((TimeoutError(), '超时'),
                                (socket.gaierror(), 'DNS'),
                                (ssl.SSLCertVerificationError(), '证书')):
            with self.subTest(cause=type(cause).__name__):
                self.assertIn(expected, describe_error(urllib.error.URLError(cause)))



if __name__ == '__main__':
    unittest.main()
