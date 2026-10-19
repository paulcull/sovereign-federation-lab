"""Real Unix PTY: shell launcher, terminal restoration, keys and persisted state."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
import uuid

from admin.registry import Registry

ROOT = Path(__file__).resolve().parents[2]


class TerminalTests(unittest.TestCase):
    def test_shell_launcher_keyboard_quit_restores_terminal_and_retains_state(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Registry(folder)
            registry.save(registry.plan('register_store', {'id': 'STORE-DE-01', 'name': 'Germany',
                'country': 'DE', 'node_count': 3}), str(uuid.uuid4()))
            master, slave = pty.openpty()
            original = termios.tcgetattr(slave)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 42, 140, 0, 0))
            environment = {**os.environ, 'TERM': 'xterm-256color', 'LAB_ADMIN_PYTHON': sys.executable}
            process = subprocess.Popen(['./lab', 'admin', '--state-dir', folder,
                '--gateway', 'http://127.0.0.1:1'], cwd=ROOT, stdin=slave, stdout=slave, stderr=slave,
                env=environment, start_new_session=True)
            output = bytearray()
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and b'LOGICAL CONTROL PLANE' not in output:
                    if select.select([master], [], [], .1)[0]:
                        output.extend(os.read(master, 65536))
                    if process.poll() is not None:
                        break
                self.assertIn(b'LOGICAL CONTROL PLANE', output)
                # Keyboard help opens and closes a real modal before quitting.
                os.write(master, b'?')
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and b'ADMIN GUIDE' not in output:
                    if select.select([master], [], [], .1)[0]:
                        output.extend(os.read(master, 65536))
                self.assertIn(b'ADMIN GUIDE', output)
                os.write(master, b'\x1b')
                time.sleep(.15)
                os.write(master, b'q')
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and process.poll() is None:
                    if select.select([master], [], [], .1)[0]:
                        output.extend(os.read(master, 65536))
                self.assertEqual(process.poll(), 0)
                self.assertEqual(termios.tcgetattr(slave), original)
                self.assertIn(b'\x1b[?1049l', output)  # Restore the normal screen.
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                os.close(master)
                os.close(slave)
            # -S disables site packages: the JSON CLI must work without Textual.
            fresh = subprocess.run([sys.executable, '-S', '-m', 'admin', '--state-dir', folder, 'config'],
                cwd=ROOT, text=True, capture_output=True, check=True)
            state = json.loads(fresh.stdout)
            self.assertEqual(state['stores'][-1]['id'], 'STORE-DE-01')
            self.assertEqual(state['stores'][-1]['node_count'], 3)
            self.assertEqual(len(state['history']), 1)


if __name__ == '__main__':
    unittest.main()
