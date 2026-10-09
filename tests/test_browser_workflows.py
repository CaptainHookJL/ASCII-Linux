"""Real-terminal text browsing against local HTTP pages, without external network."""
from contextlib import contextmanager
import fcntl
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import pty
import struct
import subprocess
import tempfile
import termios
import threading
import time
import unittest

from test_workflows import Terminal


START_MARKER = 'A' * 24
SECOND_MARKER = 'Z' * 24
# Distinct screen text prevents curses' incremental repaint from hiding a shared
# prefix in raw PTY output when history switches between already rendered pages.
START_PAGE = f'''<!doctype html><html><head><title>ASCII Browser Start</title>
<style>STYLE_CONTENT_MUST_NOT_RENDER</style></head><body>
<h1>{START_MARKER}</h1><p>Unicode: café 東京</p>
<p>find_token_7319 first occurrence</p>
<a href="/second">Second page</a>
<a href="/slow">Slow page</a>
<a href="/missing">Missing page</a>
<p>find_token_7319 second occurrence</p>
<script>SCRIPT_CONTENT_MUST_NOT_RENDER</script></body></html>'''.encode('utf-8')
SECOND_PAGE = f'''<html><head><title>ASCII Browser Second</title></head><body>
<h1>{SECOND_MARKER}</h1><a href="/index">Return home</a></body></html>'''.encode('ascii')
LATE_PAGE = b'''<html><head><title>Cancelled response</title></head><body>
<p>LATE_CANCELLED_BODY_MUST_NOT_APPEAR</p></body></html>'''
LONG_PAGE = ('<html><head><title>ASCII Long Page</title></head><body>'
             + ''.join(f'<p>ROW {i:02d}: scrolling body text</p>' for i in range(36))
             + '<p>BOTTOM_TEXT_MARKER_7319</p><a href="/second">End link</a>'
             + '</body></html>').encode('ascii')


@contextmanager
def browser_server():
    requests = []
    slow_started = threading.Event()
    release_slow = threading.Event()
    slow_finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == '/slow':
                slow_started.set()
                release_slow.wait(timeout=10)
                payload = LATE_PAGE
            else:
                payload = {'/index': START_PAGE, '/second': SECOND_PAGE,
                           '/long': LONG_PAGE}.get(self.path)
            if payload is None:
                self.send_error(404, 'Local test page does not exist')
                return
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Cancelling a page may close the HTTP connection.
            finally:
                if self.path == '/slow':
                    slow_finished.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (f'http://127.0.0.1:{server.server_port}', requests,
               slow_started, release_slow, slow_finished)
    finally:
        release_slow.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class BrowserTerminal(Terminal):
    """Use the same PTY controls for the separately runnable browser."""

    def __init__(self, home, url):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 110, 0, 0))
        self.process = subprocess.Popen(
            ['python3', '-m', 'desktop.browser', url],
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            env=dict(os.environ, TERM='xterm-256color', HOME=str(home), LANG='C.UTF-8',
                     XDG_DATA_HOME=str(Path(home) / '.local' / 'share')))
        os.close(slave)
        self.output = bytearray()


def open_url(terminal, url):
    terminal.prompt('g', 'Open web URL', url)


def leave_desktop(terminal):
    terminal.send('\x11')
    terminal.wait('Leave ASCII desktop?')
    terminal.send('y')
    if terminal.process.wait(timeout=5) != 0:
        raise AssertionError('Desktop did not exit successfully')


class BrowserWorkflowTests(unittest.TestCase):
    def test_source_wrapper_launches_from_user_apps_and_returns_to_desktop(self):
        with tempfile.TemporaryDirectory() as directory, browser_server() as fixture:
            root = Path(directory)
            url, requests, *_ = fixture
            wrapper = Path(__file__).resolve().parents[1] / 'system/ascii-browser'
            catalog = root / '.local/share/ascii-linux/apps.json'
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps([dict(
                id='ascii-browser', name='My ASCII Browser',
                command=['/bin/sh', str(wrapper), url + '/index'],
                description='Text web pages', launch_mode='terminal')]))
            terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('My ASCII Browser')
                terminal.send('\r')
                terminal.wait('ASCII Browser |')
                terminal.wait('Title: ASCII Browser Start')
                terminal.wait('Unicode: cafe ??')
                self.assertEqual(requests, ['/index'])
                terminal.send('\x1b')
                terminal.wait('/bin/sh exited with status 0')
                terminal.wait('My ASCII Browser')
                terminal.send('\x11')
                terminal.wait('Leave ASCII desktop?')
                terminal.send('y')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_standalone_ascii_pages_links_history_find_and_http_failure(self):
        with tempfile.TemporaryDirectory() as directory, browser_server() as server:
            root = Path(directory)
            url, requests, *_ = server
            terminal = BrowserTerminal(root, url + '/index')
            try:
                terminal.wait(START_MARKER)
                terminal.wait('Unicode: cafe ??')
                self.assertTrue(all(byte < 128 for byte in terminal.output))
                self.assertNotIn(b'SCRIPT_CONTENT_MUST_NOT_RENDER', terminal.output)
                self.assertNotIn(b'STYLE_CONTENT_MUST_NOT_RENDER', terminal.output)
                terminal.wait('Link 1/3: Second page')
                terminal.send('\r')
                terminal.wait(SECOND_MARKER)
                terminal.send('\x7f')
                terminal.wait(START_MARKER)
                terminal.send(']')
                terminal.wait(SECOND_MARKER)
                terminal.send('\x7f')
                terminal.wait(START_MARKER)
                terminal.prompt('/', 'Find page text', 'find_token_7319')
                terminal.wait('Match 1/2')
                terminal.send('n')
                terminal.wait('second occurrence')
                terminal.resize(29, 110)
                terminal.wait('Match 2/2')
                open_url(terminal, url + '/missing')
                terminal.wait('404')
                self.assertIsNone(terminal.process.poll())
                self.assertEqual(requests[:2], ['/index', '/second'])
                self.assertEqual(requests[-1], '/missing')
                terminal.send('\x1b')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_slow_load_cancel_and_editor_switch_preserve_both_documents(self):
        with tempfile.TemporaryDirectory() as directory, browser_server() as server:
            root = Path(directory)
            url, _, slow_started, release_slow, slow_finished = server
            terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('your console is your desktop')
                terminal.send('w')
                terminal.wait('G opens a URL')
                open_url(terminal, url + '/index')
                terminal.wait(START_MARKER)
                terminal.send('\t')
                terminal.wait('low page ->')  # First S can remain from Second page.
                terminal.send('\r')
                self.assertTrue(slow_started.wait(timeout=5))
                terminal.send(b'\x1b[20~')  # F9 must work while HTTP is waiting.
                terminal.wait('Untitled')
                terminal.send('Draft preserved during web loading')
                terminal.wait('Modified')
                terminal.send(b'\x1bOPw')
                terminal.wait('Loading: ')
                terminal.send('x')
                terminal.wait('Page load cancelled')
                release_slow.set()
                self.assertTrue(slow_finished.wait(timeout=5))
                time.sleep(.25)  # Allow the obsolete response to reach a browser tick.
                terminal.send('\x1b')
                terminal.wait('your console is your desktop')
                terminal.send('w')
                terminal.wait(START_MARKER)
                self.assertNotIn(b'LATE_CANCELLED_BODY_MUST_NOT_APPEAR', terminal.output)
                terminal.send(b'\x1b[20~')
                terminal.wait('Modified')
                terminal.prompt('\x13', 'Save as', 'browser-draft.txt')
                terminal.wait('Saved ' + str(root / 'browser-draft.txt'))
                self.assertEqual((root / 'browser-draft.txt').read_text(),
                                 'Draft preserved during web loading')
                terminal.send('\x1b')
                terminal.wait(START_MARKER)
                leave_desktop(terminal)
            finally:
                terminal.close()

    def test_bookmark_is_available_after_a_fresh_desktop_session(self):
        with tempfile.TemporaryDirectory() as directory, browser_server() as server:
            root = Path(directory)
            url, requests, *_ = server
            terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('your console is your desktop')
                terminal.send('w')
                terminal.wait('G opens a URL')
                open_url(terminal, url + '/index')
                terminal.wait(START_MARKER)
                terminal.send('b')
                terminal.wait('Bookmarked: ASCII Browser Start')
                leave_desktop(terminal)
            finally:
                terminal.close()
            terminal = Terminal(root, ascii_only=True)
            try:
                terminal.wait('your console is your desktop')
                terminal.send('w')
                terminal.wait('G opens a URL')
                terminal.send('m')
                terminal.wait('Bookmarks (1)')
                terminal.wait('ASCII Browser Start')
                terminal.send('\r')
                terminal.wait(START_MARKER)
                self.assertEqual(requests.count('/index'), 2)
                leave_desktop(terminal)
            finally:
                terminal.close()

    def test_minimum_size_page_scroll_and_resize_cancelled_url_prompt(self):
        with tempfile.TemporaryDirectory() as directory, browser_server() as server:
            url, requests, *_ = server
            terminal = BrowserTerminal(Path(directory), url + '/long')
            try:
                terminal.wait('Title: ASCII Long Page')
                terminal.resize(16, 60)
                terminal.wait('ASCII Long Page')
                terminal.send(b'\x1b[6~' * 20)
                terminal.wait('BOTTOM_TEXT_MARKER_7319')
                terminal.send('g')
                terminal.wait('Open web URL')
                terminal.send('\x15' + url + '/second')
                terminal.resize(12, 48)
                terminal.wait('Resize to at least')
                terminal.resize(16, 60)
                terminal.wait('Open web URL')
                terminal.send('\x1b')
                terminal.wait('ASCII Long Page')
                self.assertEqual(requests, ['/long'])
                terminal.send('\r')
                terminal.wait(SECOND_MARKER)
                terminal.send('\x11')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()


if __name__ == '__main__':
    unittest.main()
