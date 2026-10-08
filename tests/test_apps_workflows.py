"""Exercise the Apps section through real terminal input and saved documents."""
from pathlib import Path
import tempfile
import time
import unittest

from test_workflows import Terminal


class AppsWorkflowTests(unittest.TestCase):
    def catalog_editor_workflow(self, ascii_only):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = Terminal(root, ascii_only=ascii_only)
            try:
                terminal.wait('your console is your desktop')
                terminal.wait('Apps')
                terminal.send('a')
                terminal.wait('[all apps]')
                terminal.prompt('/', 'Search apps', 'edit')
                terminal.wait('Write and edit text')
                terminal.send('\r')
                terminal.wait('Text editor: Untitled')
                terminal.send('Apps buffer café')
                terminal.wait('Modified')
                terminal.send(b'\x1bOP')  # F1, then A opens Apps from the menu
                terminal.wait('Application launcher')
                terminal.send('A')
                terminal.wait('Write and edit text')
                terminal.prompt('/', 'Search apps', 'network')
                terminal.wait('View interfaces, addresses')
                terminal.send('\r')
                terminal.wait('INTERFACE')
                terminal.send(b'\x1b[20~')  # F9 restores the unsaved editor
                terminal.wait('Modified')
                terminal.prompt('\x13', 'Save as', 'apps-buffer.txt')
                terminal.wait('Saved ' + str(root / 'apps-buffer.txt'))
                self.assertEqual((root / 'apps-buffer.txt').read_text(), 'Apps buffer café')
                terminal.send('\x11')
                terminal.wait('View interfaces, addresses')  # editor returns to Apps
                terminal.send('\x1b')
                terminal.wait('your console is your desktop')
                terminal.send('a')
                terminal.wait('[all apps]')  # returning home cleared the search
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_ascii_catalog_search_and_editor_buffer_preservation(self):
        self.catalog_editor_workflow(True)

    def test_unicode_catalog_search_and_editor_buffer_preservation(self):
        self.catalog_editor_workflow(False)

    def test_minimum_size_home_navigation_empty_search_and_app_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('your console is your desktop')
                terminal.resize(16, 60)
                terminal.wait('Apps [A]')
                terminal.send('\t')
                terminal.wait('Text editor [F9]')
                terminal.send('\r')
                terminal.wait('Untitled')
                terminal.send('Opened from desktop')
                terminal.wait('Modified')
                terminal.prompt('\x13', 'Save as', 'from-home.txt')
                terminal.wait('Saved ' + str(root / 'from-home.txt'))
                self.assertEqual((root / 'from-home.txt').read_text(), 'Opened from desktop')
                terminal.send('\x11')
                terminal.wait('Apps [A]')
                terminal.send('a')
                terminal.wait('[all apps]')
                terminal.wait('Esc Desktop')
                terminal.prompt('/', 'Search apps', 'NoSuchApp_73ac9')
                terminal.wait('No matching apps.')
                terminal.send('\r')  # empty selection must stay on Apps
                time.sleep(.05)
                terminal.prompt('/', 'Search apps', '')
                terminal.wait('[all apps]')
                terminal.send(b'\x1bOB' * 5)  # arrows reach Network
                terminal.wait('View interfaces, addresses')
                terminal.send('\r')
                terminal.wait('INTERFACE')
                terminal.send('\x1b')
                terminal.wait('Apps [A]')
                terminal.send('\t')  # Tab wraps from Network to Files
                terminal.wait('Files [F2]')
                terminal.send('\r')
                terminal.wait('from-home.txt')
                terminal.send(b'\x1bOP')
                terminal.wait('Application launcher')
                terminal.send(b'\x1bOB' * 6 + b'\r')  # Apps menu entry
                terminal.wait('[all apps]')
                terminal.prompt('/', 'Search apps', 'F4')  # shortcuts are searchable
                terminal.wait('View your system, memory and disk information.')
                terminal.send('\r')
                terminal.wait('Hostname:')
                terminal.send(b'\x1bOPa')
                terminal.wait('View your system, memory and disk information.')
                terminal.prompt('/', 'Search apps', 'F11')
                terminal.wait('Inspect running processes')
                terminal.send('\r')
                terminal.wait('COMMAND')
                terminal.send(b'\x1bOPa')
                terminal.wait('Inspect running processes')
                terminal.prompt('/', 'Search apps', 'terminal')
                terminal.wait('Open Bash to run commands')
                terminal.send('\r')
                terminal.send("printf 'APPS_SHELL_%s\\n' OK\nexit\n")
                terminal.wait('APPS_SHELL_OK')
                terminal.wait('/bin/bash exited with status 0')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()


if __name__ == '__main__':
    unittest.main()
