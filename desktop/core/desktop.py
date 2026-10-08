"""Keyboard-first console desktop, file operations, and integrated text editing."""
import curses
import getpass
from pathlib import Path
import socket
import subprocess
import time
import unicodedata

from desktop.apps.file_manager import FileManager, preview
from desktop.apps.text_editor import TextEditor
from desktop.core.system_views import SystemApps
from desktop.utils.jobs import FileJob
from desktop.utils.system import CpuSampler, information, memory
from desktop.widgets.dialog import Dialog

LOGO = ['    _    ____   ____ ___ ___', '   / \\  / ___| / ___|_ _|_ _|',
        '  / _ \\ \\___ \\| |    | | | |', ' / ___ \\ ___) | |___ | | | |',
        '/_/   \\_\\____/ \\____|___|___|']
LINUX_LOGO = [
    ' _       ___   _   _   _   _  __  __',
    '| |     |_ _| | \\ | | | | | | \\ \\/ /',
    '| |      | |  |  \\| | | | | |  \\  /',
    '| |___   | |  | |\\  | | |_| |  /  \\',
    '|_____| |___| |_| \\_|  \\___/  /_/\\_\\',
]
LINUX_COMPACT = [
    '|   ___ |\\ | | | \\ /',
    '|    |  | \\| | |  X ',
    '|__ ___ |  | |_| / \\',
]
APPS = [('Files', 'files'), ('Text editor', 'editor'), ('Terminal', 'shell'),
        ('System information', 'system'), ('Processes', 'processes'), ('Network', 'network'),
        ('Help / About', 'help'), ('Power / Logout', 'power')]


def clean(text):
    return ''.join(c if c.isprintable() else ' ' for c in str(text))


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)


def input_path(name):
    try:
        return Path(name).expanduser()
    except RuntimeError as error:
        raise ValueError('Cannot expand path: unknown home directory or user.') from error


class Desktop:
    def __init__(self, screen, ascii_only=False):
        self.screen = screen
        self.ascii_only = ascii_only
        self.page = 'home'
        self.choice = 0
        self.browser = FileManager()
        self.cpu = CpuSampler()
        self.cpu_value = 0.0
        self.last_tick = 0
        self.message = ''
        self.lines = []
        self.offset = 0
        self.running = True
        self.dialog = None
        self.job = None
        self.editor = None
        self.editor_top = self.editor_left = 0
        self.editor_query = ''
        self.editor_return = 'home'
        self.system_apps = SystemApps(self)

    def display(self, text):
        text = clean(text)
        if self.ascii_only:
            text = text.encode('ascii', errors='replace').decode('ascii')
        return text

    def width(self, text):
        return cell_width(self.display(text))

    def text(self, y, x, text, attr=0):
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and 0 <= x < width - 1:
            # Clip by terminal cells so wide Unicode text cannot cross borders.
            available = width - x - (3 if 3 <= y < height - 3 and 2 <= x < width - 2 else 1)
            clipped = []
            for character in self.display(text):
                cells = cell_width(character)
                if cells > available:
                    break
                clipped.append(character)
                available -= cells
            try:
                self.screen.addstr(y, x, ''.join(clipped), attr)
            except curses.error:
                pass

    def frame(self, title):
        h, w = self.screen.getmaxyx()
        if self.ascii_only:
            horizontal, vertical, corners = '-', '|', '++++'
        else:
            horizontal, vertical, corners = '─', '│', '┌┐└┘'
        self.text(2, 0, corners[0] + horizontal * max(0, w - 3) + corners[1])
        self.text(2, 2, f' {title} ', curses.A_BOLD)
        for y in range(3, h - 3):
            self.text(y, 0, vertical)
            self.text(y, w - 2, vertical)
        self.text(h - 3, 0, corners[2] + horizontal * max(0, w - 3) + corners[3])

    def tick(self):
        self.system_apps.tick()
        now = time.monotonic()
        if now - self.last_tick >= 1:
            self.cpu_value = self.cpu.sample()
            self.last_tick = now
        if self.job:
            finished, _, _, result, error = self.job.snapshot()
            if finished:
                label = self.job.label
                self.job.thread.join()
                self.job = None
                self.message = f'{label}: {error}' if error else f'{label} complete'

    def render_editor(self, h, w):
        editor = self.editor
        count = max(1, h - 9)
        gutter = max(4, len(str(len(editor.lines))) + 1)
        x = 3 + gutter
        available = max(1, w - x - 3)
        self.editor_top = min(self.editor_top, editor.row)
        if editor.row >= self.editor_top + count:
            self.editor_top = editor.row - count + 1
        self.editor_left = min(self.editor_left, editor.column)
        line = editor.lines[editor.row]
        while self.editor_left < editor.column and self.width(
                line[self.editor_left:editor.column].expandtabs(4)) >= available:
            self.editor_left += 1
        for y, index in enumerate(range(self.editor_top, min(len(editor.lines), self.editor_top + count)), 4):
            self.text(y, 3, f'{index + 1:>{gutter - 1}} ', curses.A_DIM)
            self.text(y, x, editor.lines[index][self.editor_left:].expandtabs(4))
        self.text(h - 5, 3, f'Ln {editor.row + 1}, Col {editor.column + 1} | '
                  + ('Modified' if editor.dirty else 'Saved') + ' | Ctrl+Z Undo | Ctrl+Y Redo')
        self.text(h - 4, 3, 'Ctrl+S Save | Ctrl+O Open | Ctrl+N New | Ctrl+F Find')
        return (4 + editor.row - self.editor_top,
                x + self.width(line[self.editor_left:editor.column].expandtabs(4)))

    def render(self):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        cursor = None
        if h < 16 or w < 60:
            self.text(0, 0, 'Resize to at least 60 columns x 16 rows.')
            self.text(1, 0, 'Esc/Ctrl+Q closes editor or confirms desktop exit.')
            if self.dialog:
                self.dialog.render(self.text, h, w, self.width)
                cursor = self.dialog.cursor_position
            try:
                curses.curs_set(1 if cursor else 0)
                if cursor:
                    self.screen.move(min(h - 1, cursor[0]), min(w - 2, cursor[1]))
            except curses.error:
                pass
            self.screen.refresh()
            return
        self.text(0, 1, f'ASCII Linux | {getpass.getuser()}@{socket.gethostname()}', curses.A_BOLD)
        try:
            total, used = memory()
            self.text(1, 1, f'CPU {self.cpu_value:4.0f}% | RAM {used / total:4.0%} | {time.strftime("%H:%M:%S")}')
        except OSError:
            self.text(1, 1, time.strftime('%H:%M:%S'))
        title = {'home': 'Desktop', 'menu': 'Application launcher', 'files': str(self.browser.path),
                 'system': 'System information', 'preview': 'File preview', 'help': 'Help / About',
                 'power': 'Power / Logout', 'editor': 'Text editor',
                 'processes': 'Processes', 'process_details': 'Process inspection',
                 'network': 'Network', 'network_details': 'Network details'}.get(self.page, self.page)
        if self.page == 'editor' and self.editor:
            title = f'Text editor: {self.editor.path or "Untitled"}' + (' *' if self.editor.dirty else '')
        self.frame(title)
        if self.job:
            _, done, total, _, _ = self.job.snapshot()
            self.text(5, 3, self.job.label)
            if total:
                ratio = min(1, done / total)
                self.text(7, 3, '[' + '#' * int(ratio * 30) + '-' * (30 - int(ratio * 30)) + f'] {ratio:.0%}')
            self.text(9, 3, 'Operation in progress; please wait.')
        elif self.page == 'home':
            for y, line in enumerate(LOGO, 4):
                self.text(y, 3, line)
            # Keep both words visible at the supported minimum terminal height.
            linux_logo = LINUX_LOGO if h >= 20 else LINUX_COMPACT
            linux_y = 10 if h >= 20 else 9
            for y, line in enumerate(linux_logo, linux_y):
                self.text(y, 3, line)
            greeting_y = min(linux_y + len(linux_logo) + 1, h - 4)
            self.text(greeting_y, 3, 'ASCII Linux 0.1 — your console is your desktop.')
            if greeting_y + 2 <= h - 4:
                self.text(greeting_y + 2, 3, 'F1 Menu | F2 Files | F3 Bash | F9 Text editor')
        elif self.page in ('menu', 'power'):
            items = [name for name, _ in APPS] if self.page == 'menu' else ['Cancel', 'Logout', 'Reboot', 'Shutdown']
            for i, item in enumerate(items):
                self.text(4 + i, 3, ('> ' if i == self.choice else '  ') + item,
                          curses.A_REVERSE if i == self.choice else 0)
        elif self.page == 'files':
            count = max(1, h - 11)
            start = max(0, self.browser.selected - count + 1)
            for row, entry in enumerate(self.browser.entries[start:start + count], 4):
                index = start + row - 4
                try:
                    prefix = '[DIR] ' if entry.is_dir() else '      '
                except OSError as error:
                    prefix = '[?]   '
                    self.message = str(error)
                self.text(row, 3, prefix + entry.name,
                          curses.A_REVERSE if index == self.browser.selected else 0)
            try:
                self.text(h - 7, 3, self.browser.metadata())
            except OSError as error:
                self.message = str(error)
            self.text(h - 6, 3, 'Search: ' + (self.browser.query or '[all filenames]'))
            self.text(h - 5, 3, 'F5 Copy | F6 Move | F7 Mkdir | F8 Delete')
            self.text(h - 4, 3, 'E Edit | N Rename | / Search | H Hidden | Backspace Up')
        elif self.page == 'editor' and self.editor:
            cursor = self.render_editor(h, w)
        elif self.page in ('processes', 'network'):
            self.system_apps.render(self.page, h, w)
        else:
            lines = self.view_lines()
            for y, line in enumerate(lines[self.offset:self.offset + h - 8], 4):
                self.text(y, 3, line)
        self.text(h - 2, 1, self.system_apps.detail_warning(self.page) or self.message)
        footer = ('F5 Next match | F6 Save as | Esc/Ctrl+Q Close | F1 Menu | F2 Files'
                  if self.page == 'editor' else
                  'F1 Menu | F2 Files | F3 Shell | F4 System | F9 Editor | F10 Power')
        self.text(h - 1, 0, footer)
        if self.dialog:
            self.dialog.render(self.text, h, w, self.width)
            cursor = self.dialog.cursor_position
        try:
            curses.curs_set(1 if cursor else 0)
            if cursor:
                self.screen.move(cursor[0], min(w - 2, cursor[1]))
        except curses.error:
            pass
        self.screen.refresh()

    def external(self, command):
        curses.def_prog_mode()
        curses.endwin()
        try:
            result = subprocess.run(command, check=False)
            self.message = f'{command[0]} exited with status {result.returncode}'
        except OSError as error:
            self.message = str(error)
        finally:
            curses.reset_prog_mode()
            self.screen.timeout(200)
            self.screen.clear()

    def ask(self, title, initial='', confirm=False):
        self.message = ''
        self.dialog = Dialog(title, initial, confirm)
        try:
            while True:
                self.tick()
                self.render()
                try:
                    key = self.screen.get_wch()
                except curses.error:
                    continue
                finished, result = self.dialog.handle(key)
                if finished:
                    return result
        finally:
            self.dialog = None

    def confirm(self, question):
        return self.ask(question, confirm=True)

    def prompt(self, question, initial=''):
        return self.ask(question, initial)

    def unsaved(self):
        return self.editor is not None and self.editor.dirty

    def close_editor(self):
        if self.unsaved() and not self.confirm('Discard unsaved changes?'):
            return
        self.editor = None
        self.open_page(self.editor_return)

    def open_editor(self, path=None):
        # Validate the replacement before asking to discard a working document.
        replacement = TextEditor.open(path) if path is not None else TextEditor()
        if self.unsaved() and not self.confirm('Discard unsaved changes and open another document?'):
            return
        if self.page != 'editor':
            self.editor_return = self.page if self.page in ('files', 'home', 'menu') else 'home'
        self.editor = replacement
        self.editor_top = self.editor_left = 0
        self.editor_query = ''
        self.page, self.message = 'editor', ''

    def open_page(self, page):
        if page == 'editor':
            if self.editor is None:
                self.open_editor()
            else:
                self.page, self.message = 'editor', ''
            return
        self.page, self.choice, self.offset, self.message = page, 0, 0, ''
        self.system_apps.opened(page)
        if page == 'files':
            self.browser.refresh()
        elif page == 'help':
            self.lines = ['ASCII Linux 0.1 — Debian-based console desktop.',
                          'F1 Menu, F2 Files, F3 Bash, F4 System, F9 Editor, F10 Power.',
                          'F11 Processes, F12 Network (also available in F1 Menu).',
                          'Files: Enter previews; E edits; Backspace goes to parent.',
                          'H toggles hidden files; R refreshes; / filters filenames.',
                          'F5 Copy, F6 Move, F7 Mkdir, F8 Delete, N Rename.',
                          'Destinations may be relative or absolute; collisions are refused.',
                          'Directories and symlinks are supported; deletion asks first.',
                          'Editor: Ctrl+S Save, Ctrl+O Open, Ctrl+N New, Ctrl+F Find.',
                          'Editor: arrows, Home/End, Page Up/Down, Tab, Backspace/Delete.',
                          'Ctrl+Z Undo, Ctrl+Y Redo; history is bounded.',
                          'F5 finds next match; F6 saves as; Esc/Ctrl+Q closes.',
                          'Switching applications preserves the editor buffer.',
                          'Leaving/replacing an unsaved document asks before discarding.',
                          'Processes: / search, S sort, Enter inspect, K confirmed SIGTERM.',
                          'Network: arrows select, Enter addresses/routes/DNS, R refresh.',
                          'Network configuration and Wi-Fi connection are future work.',
                          'Prompts: Ctrl+U clears input; Esc cancels.',
                          'Other Linux TTYs remain available for recovery.',
                          'Installer and advanced applications are future milestones.']

    def save_editor(self, as_new=False):
        if self.editor.path and not as_new:
            self.editor.save()
        else:
            name = self.prompt('Save as (new UTF-8 file)',
                               str(self.editor.path or self.browser.path) + ('' if self.editor.path else '/'))
            if name is None or not name.strip():
                return
            path = input_path(name)
            if not path.is_absolute():
                path = self.browser.path / path
            self.editor.save(path)
        self.message = 'Saved ' + str(self.editor.path)

    def handle_editor(self, key):
        editor = self.editor
        if key in ('\x1b', '\x11'):
            self.close_editor()
        elif key == '\x1a':
            self.message = 'Undone' if editor.undo() else 'Nothing to undo'
        elif key == '\x19':
            self.message = 'Redone' if editor.redo() else 'Nothing to redo'
        elif key == '\x13':
            self.save_editor()
        elif key == curses.KEY_F6:
            self.save_editor(as_new=True)
        elif key == '\x0f':
            name = self.prompt('Open UTF-8 text file', str(self.browser.path) + '/')
            if name is not None and name.strip():
                path = input_path(name)
                self.open_editor(path if path.is_absolute() else self.browser.path / path)
        elif key == '\x0e':
            self.open_editor()
        elif key == '\x06':
            query = self.prompt('Find text (case sensitive)', self.editor_query)
            if query is not None and query:
                self.editor_query = query
                self.message = 'Match found' if editor.find(query) else 'No match found'
        elif key == curses.KEY_F5:
            if self.editor_query:
                self.message = 'Match found' if editor.find(self.editor_query) else 'No match found'
        elif key in ('\n', '\r', curses.KEY_ENTER):
            editor.insert('\n')
        elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
            editor.backspace()
        elif key == curses.KEY_DC:
            editor.delete()
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            editor.move(dc=-1 if key == curses.KEY_LEFT else 1)
        elif key in (curses.KEY_UP, curses.KEY_DOWN):
            editor.move(dr=-1 if key == curses.KEY_UP else 1)
        elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            editor.move(dr=(-1 if key == curses.KEY_PPAGE else 1) * max(1, self.screen.getmaxyx()[0] - 9))
        elif key in (curses.KEY_HOME, '\x01'):
            editor.home()
        elif key in (curses.KEY_END, '\x05'):
            editor.end()
        elif key == '\t':
            editor.insert('    ')
        elif isinstance(key, str) and key.isprintable():
            editor.insert(key)

    def start_job(self, label, operation):
        self.job = FileJob(label, operation)
        self.message = ''

    def handle_files(self, key):
        if key in (curses.KEY_UP, curses.KEY_DOWN):
            self.browser.move(-1 if key == curses.KEY_UP else 1)
        elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
            self.browser.parent()
        elif key in ('h', 'H'):
            self.browser.hidden = not self.browser.hidden
            self.browser.refresh()
        elif key in ('r', 'R'):
            self.browser.refresh()
        elif key == '/':
            query = self.prompt('Search filenames (empty shows all)', self.browser.query)
            if query is not None:
                self.browser.set_query(query)
        elif key == curses.KEY_F7:
            name = self.prompt('New directory name')
            if name:
                self.browser.mkdir(name)
                self.message = 'Directory created'
        elif key in ('n', 'N'):
            source = self.browser.selected_entry
            if source:
                name = self.prompt('Rename to (filename only)', source.name)
                if name is not None and name != source.name:
                    self.browser.rename_to(name)
                    self.message = 'Renamed'
        elif key in (curses.KEY_F5, curses.KEY_F6):
            source = self.browser.selected_entry
            if source:
                copying = key == curses.KEY_F5
                name = self.prompt(('Copy' if copying else 'Move') + ' destination (path or folder)')
                if name:
                    operation = self.browser.copy_to if copying else self.browser.move_to
                    self.start_job(('Copy' if copying else 'Move') + ' ' + source.name,
                                   lambda progress: operation(name, progress=progress))
        elif key == curses.KEY_F8:
            source = self.browser.selected_entry
            if source and self.confirm(f'Delete {source.name}? Directory contents will also be removed.'):
                self.start_job('Delete ' + source.name, self.browser.delete_selected)
        elif key in ('e', 'E'):
            source = self.browser.selected_entry
            if source:
                self.open_editor(source)
        elif key in ('\n', '\r', curses.KEY_ENTER):
            path = self.browser.activate()
            if path:
                self.lines = preview(path)
                self.page, self.offset = 'preview', 0

    def handle(self, key):
        if self.job:
            self.message = 'Operation in progress; please wait.'
            return
        if key == curses.KEY_F1:
            self.open_page('menu')
        elif key == curses.KEY_F2:
            self.open_page('files')
        elif key == curses.KEY_F3:
            self.external(['/bin/bash', '-l'])
        elif key == curses.KEY_F4:
            self.open_page('system')
        elif key == curses.KEY_F9:
            self.open_page('editor')
        elif key == curses.KEY_F10:
            self.open_page('power')
        elif key == curses.KEY_F11:
            self.open_page('processes')
        elif key == curses.KEY_F12:
            self.open_page('network')
        elif self.page == 'editor':
            self.handle_editor(key)
        elif key == '\x11':
            question = 'Leave ASCII desktop and discard unsaved changes?' if self.unsaved() else 'Leave ASCII desktop?'
            if self.confirm(question):
                self.running = False
        elif key == '\x1b':
            parent = {'preview': 'files', 'process_details': 'processes',
                      'network_details': 'network'}
            self.open_page(parent.get(self.page, 'home'))
        elif self.page in ('menu', 'power'):
            count = len(APPS) if self.page == 'menu' else 4
            if key in (curses.KEY_UP, curses.KEY_DOWN, '\t'):
                self.choice = (self.choice + (-1 if key == curses.KEY_UP else 1)) % count
            elif key in ('\n', '\r', curses.KEY_ENTER):
                if self.page == 'menu':
                    page = APPS[self.choice][1]
                    if page == 'shell':
                        self.external(['/bin/bash', '-l'])
                    else:
                        self.open_page(page)
                elif self.choice == 0:
                    self.open_page('home')
                else:
                    action = ['cancel', 'logout', 'reboot', 'poweroff'][self.choice]
                    question = f'{action.capitalize()} this session?' + (' Unsaved changes will be discarded.' if self.unsaved() else '')
                    if self.confirm(question):
                        if action == 'logout':
                            self.running = False
                        else:
                            self.external(['sudo', '/usr/bin/systemctl', action])
        elif self.page == 'files':
            self.handle_files(key)
        elif self.page in ('processes', 'process_details', 'network', 'network_details'):
            self.system_apps.handle(self.page, key)
        else:
            self.scroll_lines(key)

    def view_lines(self):
        if self.page == 'system':
            return information()
        if self.page not in ('process_details', 'network_details'):
            return self.lines
        # Preserve every address/argument; narrow terminals can scroll wrapped lines.
        width = max(1, self.screen.getmaxyx()[1] - 6)
        wrapped = []
        for line in self.lines:
            current = ''
            for character in clean(line):
                if current and self.width(current + character) > width:
                    wrapped.append(current)
                    current = ''
                current += character
            wrapped.append(current)
        return wrapped

    def scroll_lines(self, key):
        if key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            count = len(self.view_lines())
            delta = -1 if key in (curses.KEY_UP, curses.KEY_PPAGE) else 1
            if key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
                delta *= max(1, self.screen.getmaxyx()[0] - 8)
            self.offset = max(0, min(max(0, count - 1), self.offset + delta))

    def run(self):
        # Raw mode preserves Ctrl+Q/Ctrl+S instead of terminal XON/XOFF.
        curses.raw()
        curses.set_escdelay(25)
        self.screen.keypad(True)
        self.screen.timeout(200)
        while self.running:
            try:
                self.tick()
                self.render()
                try:
                    key = self.screen.get_wch()
                except curses.error:
                    continue
                self.handle(key)
            except (OSError, ValueError) as error:
                self.message = str(error)
