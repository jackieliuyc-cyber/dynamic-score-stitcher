"""Read-only static H5 preview with byte ranges for mobile video playback."""
import argparse
import mimetypes
import re
import socket
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'dist'

class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.serve(False)

    def do_GET(self):
        self.serve(True)

    def serve(self, send_body):
        name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip('/') or 'index.html'
        if '/' in name or '\\' in name or name.startswith('.'):
            return self.send_error(404)
        file = ROOT / name
        if not file.is_file() or file.is_symlink():
            return self.send_error(404)
        size = file.stat().st_size
        start, end, status = 0, size - 1, 200
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
            if not match or not any(match.groups()):
                return self.invalid_range(size)
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(int(right), end) if right else end
            else:
                start = max(0, size - int(right))
            if start >= size or start > end:
                return self.invalid_range(size)
            status = 206
        self.send_response(status)
        content_type = 'text/javascript' if file.suffix == '.js' else mimetypes.guess_type(name)[0] or 'application/octet-stream'
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if status == 206:
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
        self.end_headers()
        if send_body:
            try:
                with file.open('rb') as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        data = stream.read(min(65536, remaining))
                        if not data: break
                        self.wfile.write(data)
                        remaining -= len(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def invalid_range(self, size):
        self.send_response(416)
        self.send_header('Content-Range', 'bytes */%d' % size)
        self.send_header('Content-Length', '0')
        self.end_headers()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8780)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    except OSError as exc:
        raise SystemExit('端口无法使用，请换一个端口：python3 serve.py --port 8781\n' + str(exc))
    print('H5 本机地址：http://127.0.0.1:%d/' % args.port, flush=True)
    for interface in ['en0', 'en1']:
        try:
            ip = subprocess.check_output(['ipconfig', 'getifaddr', interface], stderr=subprocess.DEVNULL, text=True).strip()
            if ip: print('手机同一 Wi-Fi 地址：http://%s:%d/' % (ip, args.port), flush=True)
        except (OSError, subprocess.CalledProcessError): pass
    print('保持此窗口运行。按 Ctrl+C 停止。Mac 版使用原启动入口。', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
