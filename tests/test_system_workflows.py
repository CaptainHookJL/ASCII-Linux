"""Real-terminal process/network and editor history workflows on disposable data."""
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
import uuid

from test_workflows import Terminal


class SystemWorkflowTests(unittest.TestCase):
    def test_process_inspection_cancel_then_terminate_own_child_and_network_details(self):
        marker = 'ASCII_' + uuid.uuid4().hex[:8]
        child = subprocess.Popen(['/usr/bin/python3', '-c', 'import time;time.sleep(60)', marker])
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(directory)
            try:
                terminal.wait('your console is your desktop')
                terminal.send(b'\x1b[23~')  # F11
                terminal.wait('COMMAND')
                terminal.prompt('/', 'Search processes', marker)
                terminal.wait(marker)
                terminal.send('s')
                terminal.wait('memory | Search:')
                terminal.send('\r')
                terminal.wait(f'PID: {child.pid}')
                terminal.send('k')
                terminal.wait('Send SIGTERM to PID')
                terminal.send('n')
                time.sleep(.05)
                self.assertIsNone(child.poll())
                terminal.send('k')
                terminal.wait('Send SIGTERM to PID')
                terminal.send('y')
                terminal.wait(f'SIGTERM sent to PID {child.pid}')
                self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)
                terminal.send('\x1b')
                terminal.wait('COMMAND')
                terminal.send(b'\x1b[24~')  # F12
                terminal.wait('INTERFACE')
                terminal.send('\r')
                terminal.wait('MAC:')
                terminal.wait('IPv4:')
                terminal.wait('IPv6:')
                terminal.wait('DNS resolvers:')
                terminal.send('r')
                time.sleep(.05)
                terminal.send('\x1b')
                terminal.wait('INTERFACE')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)

    def test_launcher_apps_on_minimum_terminal_and_empty_process_search(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(directory, ascii_only=True)
            try:
                terminal.wait('your console is your desktop')
                terminal.resize(16, 60)
                terminal.send(b'\x1bOP')
                terminal.wait('Application launcher')
                terminal.wait('Processes')
                terminal.wait('Network')
                terminal.send(b'\x1bOB' * 4 + b'\r')
                terminal.wait('COMMAND')
                terminal.prompt('/', 'Search processes', 'NoSuchProcess_' + uuid.uuid4().hex)
                terminal.wait('No matching processes.')
                terminal.send(b'\x1b[24~')
                terminal.wait('INTERFACE')
                terminal.send('\r')
                terminal.wait('Interface:')
                terminal.send(b'\x1b[6~')  # Page Down details at small size
                terminal.wait('DNS')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_editor_undo_redo_and_saved_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = Terminal(root)
            try:
                terminal.wait('your console is your desktop')
                terminal.send(b'\x1b[20~')
                terminal.wait('Untitled')
                terminal.send('abc\x1a')
                time.sleep(.05)
                terminal.send('\x19')
                time.sleep(.05)
                terminal.send('\x1a')
                time.sleep(.05)
                terminal.prompt('\x13', 'Save as', 'undo.txt')
                terminal.wait('Saved ' + str(root / 'undo.txt'))
                self.assertEqual((root / 'undo.txt').read_text(), 'ab')
                terminal.send('\x19')
                time.sleep(.05)
                self.assertEqual((root / 'undo.txt').read_text(), 'ab')
                terminal.send('\x13')
                terminal.wait('Saved ' + str(root / 'undo.txt'))
                self.assertEqual((root / 'undo.txt').read_text(), 'abc')
                terminal.send('\x1a')
                time.sleep(.05)
                terminal.send('\x19')
                time.sleep(.05)
                terminal.send('\x11')
                terminal.wait('your console is your desktop')  # saved baseline: no discard dialog
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()


if __name__ == '__main__':
    unittest.main()
