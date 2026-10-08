"""Real-terminal registration, launch, persistence and removal of user apps."""
import json
from pathlib import Path
import shlex
import tempfile
import time
import unittest

from test_workflows import Terminal


def add_app(terminal, name, command, description=''):
    terminal.prompt('n', 'Add app: name', name)
    terminal.wait('command (quote paths with spaces)')
    terminal.send('\x15' + command + '\r')
    terminal.wait('description (optional)')
    terminal.send('\x15' + description + '\r')
    terminal.wait('Launch mode:')
    terminal.send('\x15t\r')
    terminal.wait('App added: ' + name)


class AppsWorkflowTests(unittest.TestCase):
    def user_app_workflow(self, ascii_only):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'User App.py'
            result = root / 'result.json'
            script.write_text(
                'import json, os, sys\nfrom pathlib import Path\n'
                'Path(sys.argv[1]).write_text(json.dumps({"cwd": os.getcwd(), '
                '"args": sys.argv[2:]}))\n'
                'print("CUSTOM_APP_FINISHED", flush=True)\n')
            arguments = ['two words', '$(touch PWNED)', ';', 'café']
            command = shlex.join(['python3', str(script), str(result), *arguments])
            catalog_path = root / '.local/share/ascii-linux/apps.json'
            terminal = Terminal(root, ascii_only=ascii_only)
            try:
                terminal.wait('No user apps yet.')
                terminal.wait('F9 Editor')
                terminal.send('a')
                terminal.wait('Press N to add one.')
                for name in ('Files', 'Text editor', 'Terminal', 'System information',
                             'Processes', 'Network'):
                    self.assertNotIn(name.encode(), terminal.output)
                add_app(terminal, 'My app', command, 'My own application')
                entries = json.loads(catalog_path.read_text())
                self.assertEqual([entry['name'] for entry in entries], ['My app'])
                self.assertEqual(entries[0]['command'], ['python3', str(script), str(result), *arguments])
                terminal.prompt('/', 'Search apps', 'PWNED')
                terminal.wait('PWNED')
                terminal.send('\r')
                terminal.wait('CUSTOM_APP_FINISHED')
                terminal.wait('python3 exited with status 0')
                self.assertEqual(json.loads(result.read_text()), {'cwd': str(root), 'args': arguments})
                self.assertFalse((root / 'PWNED').exists())
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

            terminal = Terminal(root, ascii_only=ascii_only)
            try:
                terminal.wait('My app')
                terminal.send('a')
                terminal.wait('My own application')
                terminal.send('d')
                terminal.wait('Remove launcher for My app?')
                terminal.send('n')
                time.sleep(.05)
                self.assertEqual(len(json.loads(catalog_path.read_text())), 1)
                terminal.send('d')
                terminal.wait('Remove launcher for My app?')
                terminal.send('y')
                terminal.wait('Launcher removed: My app')
                terminal.wait('No user apps yet.')
                self.assertEqual(json.loads(catalog_path.read_text()), [])
                self.assertTrue(script.is_file())
                self.assertTrue(result.is_file())
                terminal.send(b'\x1bOP')
                terminal.wait('Processes')
                terminal.wait('Network')
                terminal.send(b'\x1b[20~')
                terminal.wait('Text editor: Untitled')
                terminal.send('\x11')
                terminal.wait('Application launcher')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_ascii_user_app_registration_launch_persistence_and_removal(self):
        self.user_app_workflow(True)

    def test_unicode_user_app_registration_launch_persistence_and_removal(self):
        self.user_app_workflow(False)

    def test_minimum_size_scrolling_search_cancel_reload_and_editor_buffer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = Terminal(root, ascii_only=True)
            catalog_path = root / '.local/share/ascii-linux/apps.json'
            try:
                terminal.wait('No user apps yet.')
                terminal.resize(16, 60)
                terminal.wait('Apps [A]')
                terminal.send('a')
                terminal.wait('Press N to add one.')
                terminal.send('n')
                terminal.wait('Add app: name')
                terminal.send('\x1b')
                time.sleep(.05)
                self.assertFalse(catalog_path.exists())
                first_command = shlex.join(['python3', '-c',
                                            'print("FIRST_APP_FINISHED", flush=True)'])
                add_app(terminal, 'App 0', first_command, 'Launch zero')
                entries = json.loads(catalog_path.read_text())
                entries += [dict(id=str(i), name=f'App {i}', command=['true'],
                                 description=f'Launch {i}') for i in range(1, 9)]
                entries[-1]['description'] = 'Eighth launcher'
                entries[-1]['command'] = ['python3', '-c',
                    'from pathlib import Path; Path("eighth.txt").write_text("selected"); '
                    'print("EIGHTH_APP_FINISHED", flush=True)']
                catalog_path.write_text(json.dumps(entries))
                terminal.send('r')
                terminal.wait('reloaded')
                terminal.send(b'\x1bOB' * 8)
                terminal.wait('Eighth launcher')
                terminal.send('\r')
                terminal.wait('EIGHTH_APP_FINISHED')
                terminal.wait('python3 exited with status 0')
                self.assertEqual((root / 'eighth.txt').read_text(), 'selected')
                terminal.send('\t')
                terminal.wait('Launch zero')
                terminal.prompt('/', 'Search apps', 'NothingHere_73ac9')
                terminal.wait('No matching apps.')
                terminal.send('\r')
                time.sleep(.05)
                terminal.send('/')
                terminal.wait('Search apps')
                terminal.send('\x15cancelled\x1b')
                time.sleep(.05)
                terminal.send('/')
                terminal.wait('NothingHere_73ac9')
                terminal.send('\x15Eighth\r')
                terminal.wait('App 8')
                terminal.send(b'\x1b[20~')
                terminal.wait('Untitled')
                terminal.send('Preserved through user apps')
                terminal.wait('Modified')
                terminal.send(b'\x1bOPa')
                terminal.wait('Eighth launcher')
                terminal.send('\r')
                terminal.wait('EIGHTH_APP_FINISHED')
                terminal.wait('python3 exited with status 0')
                terminal.send(b'\x1b[20~')
                terminal.wait('Modified')
                terminal.prompt('\x13', 'Save as', 'preserved.txt')
                terminal.wait('Saved ' + str(root / 'preserved.txt'))
                self.assertEqual((root / 'preserved.txt').read_text(), 'Preserved through user apps')
                terminal.send('\x11')
                terminal.wait('Eighth launcher')
                terminal.send('\x1b')
                terminal.wait('Apps [A]')
                terminal.send('\t\r')
                terminal.wait('FIRST_APP_FINISHED')
                terminal.wait('python3 exited with status 0')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_missing_executable_returns_to_apps_without_losing_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = Terminal(root)
            try:
                terminal.wait('No user apps yet.')
                terminal.send('a')
                terminal.wait('Press N to add one.')
                add_app(terminal, 'Missing app', 'no-such-ascii-app_5739')
                terminal.send('\r')
                terminal.wait('No such file or directory')
                self.assertIsNone(terminal.process.poll())
                entries = json.loads((root / '.local/share/ascii-linux/apps.json').read_text())
                self.assertEqual([entry['name'] for entry in entries], ['Missing app'])
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()


if __name__ == '__main__':
    unittest.main()
