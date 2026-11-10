"""Exercise first launch and old-environment recovery without package downloads."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash')
                     and shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'POSIX launcher with FFmpeg required')
class LauncherTests(unittest.TestCase):
    def test_recovers_old_python_and_reuses_new_environment(self):
        with tempfile.TemporaryDirectory(prefix='sheet music launcher ') as temp:
            root = Path(temp)
            launcher = root / '启动动态乐谱拼接工具.command'
            shutil.copyfile(Path(__file__).resolve().parents[1] / launcher.name, launcher)
            # Fake only the old interpreter; create the replacement with real Python.
            old = root / '.venv' / 'bin'
            old.mkdir(parents=True)
            (old / 'python').write_text('#!/bin/sh\nexit 1\n')
            (old / 'python').chmod(0o755)
            marker = root / '.venv' / 'preserve-me'
            marker.write_text('old environment')
            binaries = root / 'bin'
            binaries.mkdir()
            (binaries / 'python3.12').symlink_to(sys.executable)
            (binaries / 'python3').symlink_to(old / 'python')
            env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ.get('PATH', ''))
            # These modules isolate bootstrap from network/package installation.
            for module in ('cv2', 'numpy', 'PIL'):
                (root / (module + '.py')).write_text('')
            (root / 'app.py').write_text(
                'import json, sys\nfrom pathlib import Path\n'
                'Path("launched.json").write_text(json.dumps({"version": list(sys.version_info[:2]), '
                '"args": sys.argv[1:]}))\n')
            command = ['bash', str(launcher), '--no-browser', '--port', '8768']
            first = subprocess.run(command, cwd='/', env=env, stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=90)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            data = json.loads((root / 'launched.json').read_text())
            self.assertGreaterEqual(tuple(data['version']), (3, 10))
            self.assertEqual(data['args'], command[2:])
            backups = list(root.glob('.venv.backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'preserve-me').read_text(), 'old environment')
            config = root / '.venv' / 'pyvenv.cfg'
            created = config.stat().st_mtime_ns
            second = subprocess.run(command, cwd='/', env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(config.stat().st_mtime_ns, created)
            self.assertEqual(list(root.glob('.venv.backup-*')), backups)


if __name__ == '__main__':
    unittest.main()
