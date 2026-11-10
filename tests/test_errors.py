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
from sources import describe_error, download


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

    def test_download_preserves_rate_limit_and_does_not_try_backups(self):
        metadata = {'pages': [{'cid': 1, 'duration': 10}], 'title': 'Test'}
        playback = {'durl': [{'url': 'https://a.bilivideo.com/test.mp4', 'size': 10,
                              'backup_url': ['https://b.bilivideo.com/test.mp4']}]}
        error = urllib.error.HTTPError('https://a.bilivideo.com/test.mp4', 429,
                                       'Too Many Requests', {}, None)
        with tempfile.TemporaryDirectory() as folder, \
                patch('sources.api', side_effect=[metadata, playback]), \
                patch('sources.request', side_effect=error) as request:
            with self.assertRaisesRegex(ValueError, 'HTTP 429'):
                download('BV14a4y117MF', Path(folder), lambda *_: None, lambda: None)
            request.assert_called_once()


if __name__ == '__main__':
    unittest.main()
