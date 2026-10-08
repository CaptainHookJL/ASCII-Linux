"""End-to-end curses workflows exercise user-visible operations on temporary files."""
import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest


class Terminal:
    def __init__(self, home, ascii_only=False, controlling=False):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 110, 0, 0))
        self.process = subprocess.Popen(
            ['python3', '-m', 'desktop.main'] +
            ((['--ascii'] if ascii_only else ['--unicode']) if ascii_only is not None else []),
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            preexec_fn=(lambda: fcntl.ioctl(slave, termios.TIOCSCTTY, 0)) if controlling else None,
            env=dict(os.environ, TERM='xterm-256color', HOME=str(home), LANG='C.UTF-8',
                     XDG_DATA_HOME=str(Path(home) / '.local' / 'share')))
        os.close(slave)
        self.output = bytearray()

    def send(self, text):
        self.output.clear()
        os.write(self.master, text.encode() if isinstance(text, str) else text)

    def wait(self, expected, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if expected.encode() in self.output:
                return
            if select.select([self.master], [], [], .05)[0]:
                try:
                    self.output.extend(os.read(self.master, 65536))
                except OSError:
                    break
        raise AssertionError(f'Missing {expected!r}: {bytes(self.output)!r}')

    def prompt(self, key, label, value):
        self.send(key)
        self.wait(label)
        self.send('\x15' + value + '\r')

    def resize(self, rows, columns):
        self.output.clear()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
        os.kill(self.process.pid, signal.SIGWINCH)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        os.close(self.master)


class WorkflowTests(unittest.TestCase):
    def test_copy_move_rename_search_mkdir_and_confirmed_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.txt').write_text('Original file contents')
            terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('your console is your desktop')
                terminal.send(b'\x1bOQ')
                terminal.wait('source.txt')
                terminal.prompt(b'\x1b[18~', 'New directory name', 'archive')
                terminal.wait('Directory created')
                self.assertTrue((root / 'archive').is_dir())
                terminal.prompt('/', 'Search filenames', 'source')
                terminal.wait('source.txt')
                terminal.prompt(b'\x1b[15~', 'Copy destination', 'copy.txt')
                terminal.wait('Copy source.txt complete')
                self.assertEqual((root / 'copy.txt').read_text(), 'Original file contents')
                terminal.prompt('/', 'Search filenames', 'copy')
                terminal.wait('copy.txt')
                terminal.prompt('n', 'Rename to', 'renamed.txt')
                terminal.wait('Renamed')
                self.assertFalse((root / 'copy.txt').exists())
                terminal.prompt('/', 'Search filenames', 'renamed')
                terminal.wait('renamed.txt')
                terminal.prompt(b'\x1b[17~', 'Move destination', 'archive/')
                terminal.wait('Move renamed.txt complete')
                self.assertFalse((root / 'renamed.txt').exists())
                terminal.prompt('/', 'Search filenames', '')
                terminal.wait('archive')
                terminal.send('\r')
                terminal.wait('renamed.txt')
                terminal.send(b'\x1b[19~')
                terminal.wait('Type y to confirm')
                terminal.send('n')
                time.sleep(.1)
                self.assertTrue((root / 'archive' / 'renamed.txt').exists())
                terminal.send(b'\x1b[19~')
                terminal.wait('Type y to confirm')
                terminal.send('y')
                terminal.wait('Delete renamed.txt complete')
                self.assertFalse((root / 'archive' / 'renamed.txt').exists())
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_edit_save_find_switch_apps_save_as_and_discard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'note.txt'
            original.write_text('hello world\n')
            terminal = Terminal(root)
            try:
                terminal.wait('your console is your desktop')
                terminal.send(b'\x1bOQ')
                terminal.wait('note.txt')
                terminal.send('e')
                terminal.wait('Text editor:')
                terminal.send('Edited ')
                time.sleep(.05)
                terminal.send(b'\x1bOF\rExtra\x13')
                terminal.wait('Saved ' + str(original))
                self.assertEqual(original.read_text(), 'Edited hello world\nExtra\n')
                terminal.prompt('\x06', 'Find text', 'hello')
                terminal.wait('Match found')
                terminal.send('!')
                time.sleep(.05)
                terminal.send(b'\x1bOQ')
                terminal.wait('note.txt')
                terminal.send(b'\x1b[20~')  # F9 restores the editor buffer
                terminal.wait('Modified')
                terminal.send('\x11')
                terminal.wait('Discard unsaved changes?')
                terminal.send('n')
                time.sleep(.05)
                terminal.prompt(b'\x1b[17~', 'Save as', 'alternative.txt')
                terminal.wait('Saved ' + str(root / 'alternative.txt'))
                self.assertEqual((root / 'alternative.txt').read_text(), 'Edited !hello world\nExtra\n')
                self.assertEqual(original.read_text(), 'Edited hello world\nExtra\n')
                terminal.send('*\x11')
                terminal.wait('Discard unsaved changes?')
                terminal.send('y')
                terminal.wait('note.txt')
                self.assertNotIn('*', (root / 'alternative.txt').read_text())
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_new_unicode_document_and_desktop_logout_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = Terminal(root)
            try:
                terminal.wait('your console is your desktop')
                terminal.send(b'\x1b[20~')
                terminal.wait('Untitled')
                terminal.send('café λ\nSecond line')
                terminal.wait('Modified')
                terminal.send(b'\x1bOQ')
                terminal.wait('[all filenames]')
                terminal.send('\x11')
                terminal.wait('discard unsaved changes?')
                terminal.send('n')
                time.sleep(.05)
                self.assertIsNone(terminal.process.poll())
                terminal.send(b'\x1b[20~')
                terminal.wait('café λ')
                terminal.prompt('\x13', 'Save as', 'unicode.txt')
                terminal.wait('Saved ' + str(root / 'unicode.txt'))
                self.assertEqual((root / 'unicode.txt').read_text(), 'café λ\nSecond line')
                terminal.send('\x11')
                terminal.wait('your console is your desktop')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_cancel_open_new_and_save_prompt_through_terminal_resize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            other = root / 'other.txt'
            other.write_text('Another document')
            terminal = Terminal(root)
            try:
                terminal.wait('your console is your desktop')
                terminal.send(b'\x1b[20~')
                terminal.wait('Untitled')
                terminal.send('Draft to preserve\x0e')
                terminal.wait('Discard unsaved changes')
                terminal.send('n')
                time.sleep(.05)
                terminal.prompt('\x0f', 'Open UTF-8 text file', 'other.txt')
                terminal.wait('Discard unsaved changes')
                terminal.send('n')
                time.sleep(.05)
                terminal.prompt('\x0f', 'Open UTF-8 text file', '~ascii_unknown_user_9df724c/file.txt')
                terminal.wait('Cannot expand path')
                self.assertIsNone(terminal.process.poll())
                terminal.prompt('\x13', 'Save as', '~ascii_unknown_user_9df724c/file.txt')
                terminal.wait('Cannot expand path')
                self.assertIsNone(terminal.process.poll())
                terminal.send('\x13')
                terminal.wait('Save as')
                terminal.resize(12, 48)
                terminal.wait('Resize to at least')
                terminal.resize(28, 110)
                terminal.wait('Save as')
                terminal.send('\x1b')  # cancelled saving after resizing
                time.sleep(.05)
                terminal.prompt('\x13', 'Save as', 'draft.txt')
                terminal.wait('Saved ' + str(root / 'draft.txt'))
                self.assertEqual((root / 'draft.txt').read_text(), 'Draft to preserve')
                self.assertEqual(other.read_text(), 'Another document')
                terminal.send('\x11')
                terminal.wait('your console is your desktop')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()


if __name__ == '__main__':
    unittest.main()
