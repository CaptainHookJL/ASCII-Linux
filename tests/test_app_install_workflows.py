"""Install-command workflows over real terminals and a local HTTP download."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shlex
import tempfile
import threading
import time
import unittest

from test_workflows import Terminal

PAYLOAD = (b'from pathlib import Path\n'
           b'Path("downloaded-result.txt").write_text("downloaded app ran")\n'
           b'print("DOWNLOADED_APP_FINISHED", flush=True)\n')


@contextmanager
def download_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == '/app.py':
                self.send_response(200)
                self.send_header('Content-Length', str(len(PAYLOAD)))
                self.end_headers()
                self.wfile.write(PAYLOAD)
            else:
                self.send_error(404)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def prepare_install(terminal, name, command, launch, description=''):
    terminal.prompt('i', 'Install app: name', name)
    terminal.wait('Download/install command')
    terminal.send('\x15' + command + '\r')
    terminal.wait('Launch command after installation')
    terminal.send('\x15' + launch + '\r')
    terminal.wait('App description (optional)')
    terminal.send('\x15' + description + '\r')
    terminal.wait('Review app install')


class InstallWorkflowTests(unittest.TestCase):
    def download_workflow(self, ascii_only):
        with tempfile.TemporaryDirectory() as directory, download_server() as (url, requests):
            root = Path(directory)
            downloaded = root / 'Downloaded app.py'
            catalog_path = root / '.local/share/ascii-linux/apps.json'
            command = shlex.join(['curl', '--noproxy', '*', '-fsS', url + '/app.py', '-o', str(downloaded)])
            launch = shlex.join(['python3', str(downloaded)])
            terminal = Terminal(root, ascii_only=ascii_only)
            try:
                terminal.wait('No user apps yet.')
                terminal.send('a')
                terminal.wait('Press N to add one.')
                prepare_install(terminal, 'Downloaded app', command, launch, 'Downloaded launcher')
                terminal.wait(url)
                self.assertEqual(requests, [])
                self.assertFalse(downloaded.exists())
                self.assertFalse(catalog_path.exists())
                terminal.send('y')
                terminal.wait('Installed and added: Downloaded app')
                self.assertEqual(requests, ['/app.py'])
                self.assertEqual(downloaded.read_bytes(), PAYLOAD)
                entry = json.loads(catalog_path.read_text())[0]
                self.assertEqual(entry['command'], ['python3', str(downloaded)])
                terminal.send('\r')
                terminal.wait('DOWNLOADED_APP_FINISHED')
                terminal.wait('python3 exited with status 0')
                self.assertEqual((root / 'downloaded-result.txt').read_text(), 'downloaded app ran')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_ascii_download_register_and_launch(self):
        self.download_workflow(True)

    def test_unicode_download_register_and_launch(self):
        self.download_workflow(False)

    def test_failed_download_pipeline_does_not_register_launcher(self):
        with tempfile.TemporaryDirectory() as directory, download_server() as (url, requests):
            root = Path(directory)
            terminal = Terminal(root)
            try:
                terminal.wait('No user apps yet.')
                terminal.send('a')
                terminal.wait('Press N to add one.')
                # sh exits zero on empty input; pipefail must preserve curl's failure.
                command = shlex.join(['curl', '--noproxy', '*', '-fsS', url + '/missing']) + ' | sh'
                prepare_install(terminal, 'Failed app', command, 'missing-app')
                terminal.send('y')
                terminal.wait('Install failed (exit 22); launcher not added')
                self.assertEqual(requests, ['/missing'])
                self.assertFalse((root / '.local/share/ascii-linux/apps.json').exists())
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_minimum_size_review_resize_scroll_and_cancel_never_runs_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'must-not-exist'
            command = 'printf %s ' + shlex.quote('long review ' * 24) + ' > ' + shlex.quote(str(marker))
            terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('No user apps yet.')
                terminal.resize(16, 60)
                terminal.wait('Apps [A]')
                terminal.send('a')
                terminal.wait('Press N to add one.')
                prepare_install(terminal, 'Cancelled app', command, 'true')
                terminal.wait('Y Run | N/Esc Cancel')
                terminal.resize(12, 48)
                terminal.wait('Resize to at least')
                terminal.send('y')  # review cannot run while its contents are hidden
                time.sleep(.05)
                self.assertFalse(marker.exists())
                terminal.resize(16, 60)
                terminal.wait('Review app install')
                terminal.send(b'\x1b[6~')
                terminal.wait('Launch command after installation:')
                terminal.send(b'\x1b[6~')
                terminal.wait('command succeeds.')
                terminal.resize(28, 110)  # widening a deeply scrolled review shows its content
                terminal.wait('Download/install command:')
                terminal.wait('Launch command after installation:')
                terminal.send('n')
                terminal.wait('Install cancelled')
                self.assertFalse(marker.exists())
                self.assertFalse((root / '.local/share/ascii-linux/apps.json').exists())
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_interrupted_install_restores_desktop_and_preserves_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = Terminal(root, controlling=True)
            try:
                terminal.wait('No user apps yet.')
                terminal.send(b'\x1b[20~')
                terminal.wait('Untitled')
                terminal.send('Preserved while installing')
                terminal.wait('Modified')
                terminal.send(b'\x1bOPa')
                terminal.wait('Press N to add one.')
                prepare_install(terminal, 'Interrupted app',
                                "printf 'INSTALL_%s\\n' RUNNING; sleep 30", 'true')
                terminal.send('y')
                terminal.wait('INSTALL_RUNNING')
                terminal.send('\x03')
                terminal.wait('launcher not added')
                self.assertIsNone(terminal.process.poll())
                self.assertFalse((root / '.local/share/ascii-linux/apps.json').exists())
                terminal.send(b'\x1b[20~')
                terminal.wait('Modified')
                terminal.prompt('\x13', 'Save as', 'install-draft.txt')
                terminal.wait('Saved ' + str(root / 'install-draft.txt'))
                self.assertEqual((root / 'install-draft.txt').read_text(), 'Preserved while installing')
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
