"""Keyboard-first console desktop. All privileged actions are explicit."""
import curses
import getpass
import os
from pathlib import Path
import socket
import subprocess
import time

from desktop.apps.file_manager import FileManager, preview
from desktop.utils.system import CpuSampler, information, memory

LOGO = ['    _    ____   ____ ___ ___', '   / \\  / ___| / ___|_ _|_ _|',
        '  / _ \\ \\___ \\| |    | | | |', ' / ___ \\ ___) | |___ | | | |',
        '/_/   \\_\\____/ \\____|___|___|']
APPS = ['Files', 'Terminal', 'System information', 'Help / About', 'Power / Logout']


def clean(text):
    return ''.join(c if c.isprintable() else ' ' for c in str(text))


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

    def text(self, y, x, text, attr=0):
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and 0 <= x < width - 1:
            text = clean(text)
            if self.ascii_only:
                text = text.encode('ascii', errors='replace').decode('ascii')
            try:
                self.screen.addnstr(y, x, text, max(0, width - x - 1), attr)
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

    def render(self):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        if h < 16 or w < 60:
            self.text(0, 0, 'Resize to at least 60 columns x 16 rows. Ctrl+Q exits.')
            self.screen.refresh()
            return
        self.text(0, 1, f'ASCII Linux | {getpass.getuser()}@{socket.gethostname()}', curses.A_BOLD)
        try:
            total, used = memory()
            self.text(1, 1, f'CPU {self.cpu_value:4.0f}% | RAM {used / total:4.0%} | {time.strftime("%H:%M:%S")}')
        except OSError:
            self.text(1, 1, time.strftime('%H:%M:%S'))
        self.frame({'home': 'Desktop', 'menu': 'Application launcher', 'files': str(self.browser.path),
                    'system': 'System information', 'preview': 'File preview', 'help': 'Help / About',
                    'power': 'Power / Logout'}.get(self.page, self.page))
        if self.page == 'home':
            for y, line in enumerate(LOGO, 4):
                self.text(y, 3, line)
            self.text(10, 3, 'ASCII Linux 0.1 — your console is your desktop.')
            self.text(12, 3, 'Press F1 to launch an application. F3 opens Bash.')
        elif self.page in ('menu', 'power'):
            items = APPS if self.page == 'menu' else ['Cancel', 'Logout', 'Reboot', 'Shutdown']
            for i, item in enumerate(items):
                self.text(4 + i, 3, ('> ' if i == self.choice else '  ') + item,
                          curses.A_REVERSE if i == self.choice else 0)
        elif self.page == 'files':
            count = max(1, h - 9)
            start = max(0, self.browser.selected - count + 1)
            for row, entry in enumerate(self.browser.entries[start:start + count], 4):
                index = start + row - 4
                self.text(row, 3, ('[DIR] ' if entry.is_dir() else '      ') + entry.name,
                          curses.A_REVERSE if index == self.browser.selected else 0)
            try:
                self.text(h - 5, 3, self.browser.metadata())
            except OSError as error:
                self.message = str(error)
            self.text(h - 4, 3, 'Enter Open | Backspace Parent | H Hidden | R Refresh')
        else:
            lines = information() if self.page == 'system' else self.lines
            for y, line in enumerate(lines[self.offset:self.offset + h - 8], 4):
                self.text(y, 3, line)
        self.text(h - 2, 1, self.message)
        self.text(h - 1, 0, 'F1 Menu | F2 Files | F3 Shell | F4 System | F10 Power | Esc Back')
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

    def confirm(self, question):
        self.message = question + ' Type y to confirm; any other key cancels.'
        self.render()
        self.screen.timeout(-1)
        try:
            return self.screen.getch() in (ord('y'), ord('Y'))
        finally:
            self.screen.timeout(200)
            self.message = ''

    def open_page(self, page):
        self.page, self.choice, self.offset, self.message = page, 0, 0, ''
        if page == 'files':
            self.browser.refresh()
        elif page == 'help':
            self.lines = ['ASCII Linux 0.1 — Debian-based console desktop.',
                          'Arrow keys navigate; Enter selects; Esc returns to the desktop.',
                          'F3 launches Bash. Type exit to return here.',
                          'Files: H toggles hidden entries, R refreshes, Backspace goes up.',
                          'Enter previews regular text files; Up/Down scroll the preview.',
                          'Ctrl+Q or Power > Logout leaves this session.',
                          'On Linux consoles Ctrl+Alt+F2 opens a recovery TTY.',
                          'Power actions use sudo and normal system permissions.',
                          'Installer and advanced applications are future milestones.']

    def handle(self, key):
        if key == 17:
            if self.confirm('Leave ASCII desktop?'):
                self.running = False
        elif key == curses.KEY_F1:
            self.open_page('menu')
        elif key == curses.KEY_F2:
            self.open_page('files')
        elif key == curses.KEY_F3:
            self.external(['/bin/bash', '-l'])
        elif key == curses.KEY_F4:
            self.open_page('system')
        elif key == curses.KEY_F10:
            self.open_page('power')
        elif key == 27:
            self.open_page('home')
        elif self.page in ('menu', 'power'):
            count = len(APPS) if self.page == 'menu' else 4
            if key in (curses.KEY_UP, curses.KEY_DOWN, 9):
                self.choice = (self.choice + (-1 if key == curses.KEY_UP else 1)) % count
            elif key in (10, 13, curses.KEY_ENTER):
                if self.page == 'menu':
                    page = ['files', 'shell', 'system', 'help', 'power'][self.choice]
                    if page == 'shell':
                        self.external(['/bin/bash', '-l'])
                    else:
                        self.open_page(page)
                elif self.choice == 0:
                    self.open_page('home')
                elif self.choice == 1:
                    if self.confirm('Logout?'):
                        self.running = False
                else:
                    action = 'reboot' if self.choice == 2 else 'poweroff'
                    if self.confirm(f'{action.capitalize()} this machine?'):
                        self.external(['sudo', '/usr/bin/systemctl', action])
        elif self.page == 'files':
            if key in (curses.KEY_UP, curses.KEY_DOWN):
                self.browser.move(-1 if key == curses.KEY_UP else 1)
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self.browser.parent()
            elif key in (ord('h'), ord('H')):
                self.browser.hidden = not self.browser.hidden
                self.browser.refresh()
            elif key in (ord('r'), ord('R')):
                self.browser.refresh()
            elif key in (10, 13, curses.KEY_ENTER):
                path = self.browser.activate()
                if path:
                    self.lines = preview(path)
                    self.page, self.offset = 'preview', 0
        elif key in (curses.KEY_UP, curses.KEY_DOWN):
            self.offset = max(0, min(max(0, len(self.lines) - 1),
                                     self.offset + (-1 if key == curses.KEY_UP else 1)))

    def run(self):
        # Raw mode preserves Ctrl+Q instead of consuming it as terminal XON.
        curses.raw()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.screen.keypad(True)
        self.screen.timeout(200)
        while self.running:
            now = time.monotonic()
            if now - self.last_tick >= 1:
                self.cpu_value = self.cpu.sample()
                self.last_tick = now
            try:
                self.render()
                key = self.screen.getch()
                if key != -1:
                    self.handle(key)
            except (OSError, ValueError) as error:
                self.message = str(error)
