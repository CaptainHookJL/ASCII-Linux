"""Functional tests for Linux data, file browsing, and a real curses PTY."""
import curses
import fcntl
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import tempfile
import termios
import time
import unittest

from desktop.apps.file_manager import FileManager, preview
from desktop.utils.system import CpuSampler, information, memory


class FilesTests(unittest.TestCase):
    def test_navigation_hidden_and_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'folder').mkdir()
            (root / 'hello.txt').write_text('hello\nworld\n')
            (root / '.secret').write_text('hidden')
            browser = FileManager(root)
            self.assertEqual([p.name for p in browser.entries], ['folder', 'hello.txt'])
            browser.activate()
            self.assertEqual(browser.path, root / 'folder')
            browser.parent()
            browser.hidden = True
            browser.refresh()
            self.assertIn('.secret', [p.name for p in browser.entries])
            browser.selected = next(i for i, p in enumerate(browser.entries) if p.name == 'hello.txt')
            self.assertIn('bytes', browser.metadata())
            self.assertEqual(preview(browser.activate()), ['hello', 'world'])

    def test_preview_is_bounded_and_rejects_special_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'large.txt'
            path.write_text('x' * 20000)
            self.assertIn('limited', preview(path)[-1])
            path.write_bytes(b'abc\x00def')
            self.assertIn('Binary', preview(path)[0])
            fifo = root / 'pipe'
            os.mkfifo(fifo)
            self.assertIn('regular files only', preview(fifo)[0])


class SystemTests(unittest.TestCase):
    def test_real_linux_statistics(self):
        total, used = memory()
        self.assertGreater(total, 0)
        self.assertGreaterEqual(used, 0)
        self.assertLessEqual(used, total)
        stats = '\n'.join(information())
        for field in ['Hostname:', 'Kernel:', 'CPU:', 'Memory:', 'Root disk:', 'Uptime:', 'Network:']:
            self.assertIn(field, stats)
        sampler = CpuSampler()
        sampler.sample()
        time.sleep(0.02)
        self.assertTrue(0 <= sampler.sample() <= 100)


class TerminalTests(unittest.TestCase):
    def test_ascii_keyboard_workflow_and_shell_return(self):
        self.workflow(True)

    def test_unicode_keyboard_workflow_and_shell_return(self):
        self.workflow(False)

    def workflow(self, ascii_only):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 100, 0, 0))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'example.txt').write_text('Functional preview content')
            environment = dict(os.environ, TERM='xterm-256color', HOME=directory)
            command = ['python3', '-m', 'desktop.main'] + (['--ascii'] if ascii_only else ['--unicode'])
            process = subprocess.Popen(command,
                                       stdin=slave, stdout=slave, stderr=slave,
                                       env=environment, start_new_session=True)
            os.close(slave)
            output = bytearray()

            def wait_for(text, timeout=5):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if text.encode() in output:
                        return
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            output.extend(os.read(master, 65536))
                        except OSError:
                            break
                self.fail(f'Missing {text!r}. Terminal output: {bytes(output)!r}')

            def send(value):
                output.clear()
                os.write(master, value)

            try:
                wait_for('your console is your desktop')
                send(b'\x1bOP')  # xterm F1
                wait_for('Application launcher')
                send(b'\x1bOQ')  # F2
                wait_for('example.txt')
                send(b'\r')
                wait_for('Functional preview content')
                send(b'\x1bOS')  # F4
                wait_for('Kernel:')
                send(b'\x1bOR')  # F3
                time.sleep(0.2)
                os.write(master, b'exit\n')
                wait_for('/bin/bash exited with status 0')
                send(b'\x1b[21~')  # F10
                wait_for('Power / Logout')
                send(b'\x1bOB\x1bOB\r')  # select reboot
                wait_for('Type y to confirm')
                send(b'n')  # exercise cancellation; never invoke systemctl
                time.sleep(0.2)
                send(b'\x11')
                wait_for('Leave ASCII desktop?')
                os.write(master, b'y')
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)


if __name__ == '__main__':
    unittest.main()
