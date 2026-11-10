"""Verify duplicate launches and port collisions without touching video files."""
import errno
from http.server import ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch

import app


class StartupTests(unittest.TestCase):
    def test_reuses_healthy_instance_and_rejects_other_project(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            reused, url = app.select_server(port)
            self.assertIsNone(reused)
            self.assertEqual(url, f"http://127.0.0.1:{port}")
            # A different project has the same API but a different identity.
            with patch.object(app.Handler, "json", lambda handler, status, data:
                              original_json(handler, status, dict(data, instance="other-project"))):
                self.assertFalse(app.is_running_instance(port))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_default_skips_busy_port(self):
        busy = OSError(errno.EADDRINUSE, "Address already in use")
        sentinel = unittest.mock.Mock(server_port=8766)
        with patch.object(app, "ThreadingHTTPServer", side_effect=[busy, sentinel]) as bind, \
                patch.object(app, "is_running_instance", return_value=False):
            server, url = app.select_server()
        self.assertIs(server, sentinel)
        self.assertEqual(url, "http://127.0.0.1:8766")
        self.assertEqual([call.args[0][1] for call in bind.call_args_list], [8765, 8766])

    def test_explicit_busy_port_does_not_silently_change(self):
        with patch.object(app, "ThreadingHTTPServer", side_effect=OSError(errno.EADDRINUSE, "busy")), \
                patch.object(app, "is_running_instance", return_value=False):
            with self.assertRaisesRegex(SystemExit, "指定端口 8765"):
                app.select_server(8765)

    def test_reuses_fallback_even_when_first_port_is_free(self):
        with patch.object(app, "is_running_instance", side_effect=lambda port: port == 8766), \
                patch.object(app, "ThreadingHTTPServer") as bind:
            server, url = app.select_server()
        self.assertIsNone(server)
        self.assertEqual(url, "http://127.0.0.1:8766")
        bind.assert_not_called()


original_json = app.Handler.json
