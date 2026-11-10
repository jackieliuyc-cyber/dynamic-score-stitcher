"""Downloader boundaries and a real yt-dlp transfer of newly generated test media."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from yt_dlp.extractor.bilibili import BiliBiliIE
from yt_dlp.utils import DownloadError
import sources


class DownloaderTests(unittest.TestCase):
    def test_refusal_does_not_reuse_existing_video(self):
        with tempfile.TemporaryDirectory() as temp, patch('yt_dlp.YoutubeDL') as factory:
            folder = Path(temp)
            original = folder / 'source.mp4'
            original.write_bytes(b'old file must not be returned')
            client = factory.return_value.__enter__.return_value
            client.extract_info.side_effect = DownloadError('HTTP Error 412: https://example.test/?secret=x')
            with self.assertRaisesRegex(ValueError, 'HTTP 412') as error:
                sources.download('BV14a4y117MF', folder, lambda *_: None, lambda: None)
            self.assertNotIn('secret', str(error.exception))
            client.extract_info.assert_called_once()
            options = factory.call_args.args[0]
            self.assertFalse(options['cachedir'])
            self.assertFalse(options['continuedl'])
            self.assertIsNone(options['cookiesfrombrowser'])
            self.assertIsNone(options['cookiefile'])
            self.assertEqual(original.read_bytes(), b'old file must not be returned')
            self.assertEqual(list(folder.iterdir()), [original])

    def test_cancel_during_transfer_cleans_partial_file(self):
        class Cancelled(Exception):
            pass
        cancelled = False
        def check():
            if cancelled:
                raise Cancelled()
        with tempfile.TemporaryDirectory() as temp, patch('yt_dlp.YoutubeDL') as factory:
            def transfer(*args, **kwargs):
                nonlocal cancelled
                options = factory.call_args.args[0]
                Path(options['outtmpl'] + '.part').write_bytes(b'partial')
                cancelled = True
                options['progress_hooks'][0]({'status': 'downloading', 'downloaded_bytes': 7})
            factory.return_value.__enter__.return_value.extract_info.side_effect = transfer
            with self.assertRaises(Cancelled):
                sources.download('BV14a4y117MF', Path(temp), lambda *_: None, check)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_duration_and_unknown_size_limits(self):
        for metadata, event, message in [({'duration': 1801}, None, '30 分钟'),
                                          ({'duration': 10}, {'downloaded_bytes': sources.MAX_BYTES + 1}, '1 GB')]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temp, \
                    patch('yt_dlp.YoutubeDL') as factory:
                def transfer(*args, **kwargs):
                    options = factory.call_args.args[0]
                    options['match_filter'](metadata, incomplete=False)
                    options['progress_hooks'][0](dict(event, status='downloading'))
                factory.return_value.__enter__.return_value.extract_info.side_effect = transfer
                with self.assertRaisesRegex(ValueError, message):
                    sources.download('BV14a4y117MF', Path(temp), lambda *_: None, lambda: None)
                self.assertEqual(list(Path(temp).iterdir()), [])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_real_downloader_fetches_fresh_media_and_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / 'new-fixture.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=white:s=64x64:r=10:d=1', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', str(fixture)], check=True, timeout=20)
            payload = fixture.read_bytes()
            requests = []
            class Media(BaseHTTPRequestHandler):
                def do_GET(self):
                    requests.append(self.path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                def log_message(self, *_):
                    pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Media)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            folder = root / 'job'
            folder.mkdir()
            (folder / 'source.mp4').write_bytes(b'obsolete data')
            info = {'id': 'fixture', 'title': 'New synthetic video', 'duration': 1,
                    'formats': [{'format_id': 'test', 'ext': 'mp4', 'vcodec': 'h264',
                                 'acodec': 'none', 'height': 64, 'width': 64,
                                 'url': f'http://127.0.0.1:{server.server_port}/new.mp4'}]}
            try:
                # Only source-site discovery is mocked; yt-dlp performs the actual transfer.
                with patch.object(BiliBiliIE, '_real_extract', return_value=info):
                    path, metadata = sources.download('BV14a4y117MF', folder, lambda *_: None, lambda: None)
                self.assertEqual(requests, ['/new.mp4'])
                self.assertEqual(path.read_bytes(), payload)
                self.assertEqual(metadata['title'], 'New synthetic video')
                self.assertEqual(sources.probe(path)['width'], 64)
                sources.preview(path, folder / 'preview.jpg')
                self.assertTrue((folder / 'preview.jpg').is_file())
                self.assertFalse(list(folder.glob('.download-*')))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
