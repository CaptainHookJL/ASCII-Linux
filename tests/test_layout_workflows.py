"""ASCII layout browsing through real terminals and local HTTP fixtures."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import select
import tempfile
import threading
import time
import unittest

from test_browser_workflows import BrowserTerminal, leave_desktop, open_url
from test_workflows import Terminal


HEADER = 'LAYOUT_HEADER_7319'
MAIN = 'MAIN_COLUMN_7319'
SIDE = 'SIDE_COLUMN_8462'
END = 'LAYOUT_END_5298'
FIND = 'find_marker_7351'


def layout_html(long=False):
    extra = ''.join(f'<p>Main row {index:02d}: enough text to scroll.</p>'
                    for index in range(24)) if long else ''
    return f'''<!doctype html><html><head><title>ASCII Layout Fixture</title>
    <style>.columns {{ display: grid; grid-template-columns: 2fr 1fr; }}</style>
    </head><body><header><h1>{HEADER}</h1>
    <nav><a href="/first">First destination</a>
    <a href="/second">Second destination</a></nav></header>
    <div class="columns" style="display:grid;grid-template-columns:2fr 1fr">
    <main><h2>{MAIN}</h2><p>Main copy: cafe and ordinary ASCII text.</p>
    <table><thead><tr><th>Item</th><th>Value</th></tr></thead><tbody>
    <tr><td>Apples</td><td>17</td></tr>
    <tr><td>Table</td><td>{FIND} table result</td></tr>
    </tbody></table>{extra}</main>
    <aside><h2>{SIDE}</h2><p>{FIND} sidebar result</p>
    <p>Sidebar words remain readable when the columns stack.</p></aside></div>
    <footer><p>{END}</p></footer></body></html>'''.encode('ascii')


@contextmanager
def layout_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            payload = {
                '/layout': layout_html(), '/long-layout': layout_html(long=True),
                '/first': b'<html><title>First target</title><p>FIRST_TARGET_1902</p></html>',
                '/second': b'<html><title>Second target</title><p>SECOND_TARGET_4863</p></html>',
            }.get(self.path)
            if payload is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

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


class ASCIIScreen:
    """Record the cursor movements curses emits, so column checks use the screen."""
    def __init__(self, rows=28, columns=110):
        self.pending = ''
        self.row = self.column = 0
        self.last = ' '
        self.resize(rows, columns)

    def resize(self, rows, columns):
        self.rows, self.columns = rows, columns
        self.cells = [[' '] * columns for _ in range(rows)]
        self.row = min(self.row, rows - 1)
        self.column = min(self.column, columns - 1)
        self.top, self.bottom = 0, rows - 1

    def _scroll(self, amount):
        amount = max(-(self.bottom - self.top + 1),
                     min(self.bottom - self.top + 1, amount))
        rows = self.cells[self.top:self.bottom + 1]
        blanks = [[' '] * self.columns for _ in range(abs(amount))]
        self.cells[self.top:self.bottom + 1] = (rows[amount:] + blanks if amount > 0 else
                                                blanks + rows[:amount])

    def _write(self, char):
        if 0 <= self.row < self.rows and 0 <= self.column < self.columns:
            self.cells[self.row][self.column] = char
        self.last = char
        self.column = min(self.columns, self.column + 1)

    def _control(self, arguments, command):
        private = arguments.startswith('?')
        values = [int(item or '0') for item in arguments.lstrip('?').split(';')]
        amount = values[0] or 1
        if private:
            if command == 'h' and 1049 in values:
                self.cells = [[' '] * self.columns for _ in range(self.rows)]
                self.row = self.column = 0
            return
        if command in ('H', 'f'):
            self.row = min(self.rows - 1, max(0, (values[0] or 1) - 1))
            self.column = min(self.columns - 1, max(0, (values[1] if len(values) > 1 else 1) - 1))
        elif command == 'A':
            self.row = max(0, self.row - amount)
        elif command == 'B':
            self.row = min(self.rows - 1, self.row + amount)
        elif command == 'C':
            self.column = min(self.columns - 1, self.column + amount)
        elif command == 'D':
            self.column = max(0, self.column - amount)
        elif command == 'G':
            self.column = min(self.columns - 1, amount - 1)
        elif command == 'd':
            self.row = min(self.rows - 1, amount - 1)
        elif command == 'J':
            if values[0] in (2, 3):
                self.cells = [[' '] * self.columns for _ in range(self.rows)]
            elif values[0] == 0:
                self.cells[self.row][self.column:] = [' '] * (self.columns - self.column)
                for row in range(self.row + 1, self.rows):
                    self.cells[row] = [' '] * self.columns
        elif command == 'K':
            start, end = ((0, self.columns) if values[0] == 2 else
                          (0, self.column + 1) if values[0] == 1 else
                          (self.column, self.columns))
            self.cells[self.row][start:end] = [' '] * (end - start)
        elif command == 'X':
            end = min(self.columns, self.column + amount)
            self.cells[self.row][self.column:end] = [' '] * (end - self.column)
        elif command == 'b':
            for _ in range(amount):
                self._write(self.last)
        elif command == 'r':
            self.top = (values[0] or 1) - 1
            self.bottom = (values[1] if len(values) > 1 else self.rows) - 1
        elif command in ('S', 'T'):
            self._scroll(amount if command == 'S' else -amount)

    def feed(self, data):
        value = self.pending + data.decode('ascii', 'replace')
        self.pending = ''
        position = 0
        while position < len(value):
            character = value[position]
            if character == '\x1b':
                tail = value[position:]
                if len(tail) < 2:
                    break
                if tail.startswith('\x1b['):
                    match = re.match(r'\x1b\[([0-9;?]*)([@-~])', tail)
                    if match is None:
                        break
                    self._control(match[1], match[2])
                    position += len(match[0])
                elif tail[1] in '()':
                    if len(tail) < 3:
                        break
                    position += 3  # Terminal character set selection.
                elif tail[1] == ']':
                    match = re.match(r'\x1b\].*?(?:\x07|\x1b\\)', tail, re.S)
                    if match is None:
                        break
                    position += len(match[0])
                else:
                    position += 2
                continue
            if character == '\r':
                self.column = 0
            elif character == '\n':
                if self.row == self.bottom:
                    self._scroll(1)
                else:
                    self.row = min(self.rows - 1, self.row + 1)
            elif character == '\b':
                self.column = max(0, self.column - 1)
            elif character == '\t':
                self.column = min(self.columns - 1, (self.column // 8 + 1) * 8)
            elif ' ' <= character <= '~':
                self._write(character)
            position += 1
        self.pending = value[position:]

    def lines(self):
        return [''.join(row) for row in self.cells]


class RecordedTerminal:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.screen = ASCIIScreen()
        self.recorded = 0
        self.raw = bytearray()

    def _record(self):
        data = self.output[self.recorded:]
        self.screen.feed(data)
        self.raw.extend(data)
        self.recorded = len(self.output)

    def send(self, value):
        self._record()
        super().send(value)
        self.recorded = 0

    def wait(self, *args, **kwargs):
        super().wait(*args, **kwargs)
        self._record()

    def resize(self, rows, columns):
        self._record()
        super().resize(rows, columns)
        self.screen.resize(rows, columns)
        self.recorded = 0

    def wait_screen(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._record()
            lines = self.screen.lines()
            if predicate(lines):
                return lines
            if select.select([self.master], [], [], .05)[0]:
                try:
                    self.output.extend(os.read(self.master, 65536))
                except OSError:
                    break
        raise AssertionError('Screen condition not met:\n' + '\n'.join(self.screen.lines()))


class LayoutBrowserTerminal(RecordedTerminal, BrowserTerminal):
    pass


class LayoutDesktopTerminal(RecordedTerminal, Terminal):
    pass


class LayoutWorkflowTests(unittest.TestCase):
    def test_wide_columns_tables_mode_toggle_and_link_navigation(self):
        with tempfile.TemporaryDirectory() as directory, layout_server() as fixture:
            url, requests = fixture
            terminal = LayoutBrowserTerminal(Path(directory), url + '/layout')
            try:
                terminal.wait(HEADER)
                screen = terminal.wait_screen(lambda lines: any(MAIN in line and SIDE in line for line in lines))
                combined = next(line for line in screen if MAIN in line and SIDE in line)
                self.assertGreater(combined.index(SIDE), combined.index(MAIN) + len(MAIN))
                terminal.send(b'\x1b[6~')
                terminal.wait_screen(lambda lines: any('Apples' in line and '17' in line and '|' in line for line in lines))
                terminal.send('l')
                terminal.wait_screen(lambda lines: any('Layout: Text' in line for line in lines))
                screen = terminal.wait_screen(lambda lines: any(MAIN in line for line in lines))
                self.assertFalse(any(MAIN in line and SIDE in line for line in screen))
                terminal.send('l')
                terminal.wait_screen(lambda lines: any('Layout: ASCII' in line for line in lines))
                terminal.wait_screen(lambda lines: any(MAIN in line and SIDE in line for line in lines))
                terminal.send('\t')
                terminal.wait('Second destination')
                terminal.send('\r')
                terminal.wait('SECOND_TARGET_4863')
                self.assertEqual(requests, ['/layout', '/second'])
                self.assertTrue(all(byte < 128 for byte in terminal.raw))
                terminal.send('\x1b')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_search_reflows_sidebar_and_table_at_narrow_width(self):
        with tempfile.TemporaryDirectory() as directory, layout_server() as fixture:
            url, _ = fixture
            terminal = LayoutBrowserTerminal(Path(directory), url + '/long-layout')
            try:
                terminal.wait(HEADER)
                terminal.prompt('/', 'Find page text', FIND)
                terminal.wait_screen(lambda lines: any('Match 1/2' in line for line in lines))
                terminal.wait_screen(lambda lines: any(FIND in line for line in lines))
                terminal.send('n')
                terminal.wait_screen(lambda lines: any('Match 2/2' in line for line in lines))
                terminal.wait_screen(lambda lines: any(FIND in line for line in lines))
                terminal.resize(18, 60)
                terminal.wait_screen(lambda lines: any('Match 2/2' in line for line in lines))
                terminal.wait_screen(lambda lines: any(FIND in line for line in lines))
                terminal.send(b'\x1bOF')
                terminal.wait(END)
                terminal.send(b'\x1bOH')
                terminal.wait(HEADER)
                terminal.send('n')
                terminal.wait_screen(lambda lines: any('Match 1/2' in line for line in lines))
                terminal.wait_screen(lambda lines: any(FIND in line for line in lines))
                self.assertTrue(all(byte < 128 for byte in terminal.raw))
                terminal.send('\x1b')
                self.assertEqual(terminal.process.wait(timeout=5), 0)
            finally:
                terminal.close()

    def test_switching_desktop_tools_keeps_layout_mode_and_editor_draft(self):
        with tempfile.TemporaryDirectory() as directory, layout_server() as fixture:
            home = Path(directory)
            (home / 'layout-note.txt').write_text('Existing note')
            url, requests = fixture
            terminal = LayoutDesktopTerminal(home, ascii_only=True)
            try:
                terminal.wait('your console is your desktop')
                terminal.send('w')
                terminal.wait('G opens a URL')
                open_url(terminal, url + '/layout')
                terminal.wait(HEADER)
                terminal.send('l')
                terminal.wait_screen(lambda lines: any('Layout: Text' in line for line in lines))
                terminal.send(b'\x1b[20~')
                terminal.wait('Untitled')
                terminal.send('Keep my draft through layout browsing')
                terminal.wait('Modified')
                terminal.send(b'\x1bOQ')
                terminal.wait('layout-note.txt')
                terminal.send(b'\x1bOPw')
                terminal.wait(HEADER)
                terminal.send('l')
                terminal.wait_screen(lambda lines: any('Layout: ASCII' in line for line in lines))
                terminal.wait_screen(lambda lines: any(MAIN in line and SIDE in line for line in lines))
                terminal.send(b'\x1b[20~')
                terminal.wait('Modified')
                terminal.prompt('\x13', 'Save as', 'preserved-draft.txt')
                terminal.wait('Saved ' + str(home / 'preserved-draft.txt'))
                self.assertEqual((home / 'preserved-draft.txt').read_text(),
                                 'Keep my draft through layout browsing')
                self.assertEqual(requests, ['/layout'])
                terminal.send('\x1b')
                terminal.wait(HEADER)
                leave_desktop(terminal)
            finally:
                terminal.close()


if __name__ == '__main__':
    unittest.main()
