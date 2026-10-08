"""Read-only file browser for the first live milestone."""
from pathlib import Path
import pwd
import stat
from datetime import datetime


class FileManager:
    def __init__(self, path=None):
        self.path = Path(path or Path.home()).resolve()
        self.hidden = False
        self.selected = 0
        self.entries = []
        self.refresh()

    def refresh(self):
        entries = [p for p in self.path.iterdir() if self.hidden or not p.name.startswith('.')]
        self.entries = sorted(entries, key=lambda p: (not p.is_dir(), p.name.casefold()))
        self.selected = min(self.selected, max(0, len(self.entries) - 1))

    def move(self, delta):
        self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))

    def parent(self):
        self.navigate(self.path.parent)

    def navigate(self, path):
        old = self.path
        self.path = Path(path).resolve()
        try:
            self.refresh()
        except OSError:
            self.path = old
            raise
        self.selected = 0

    def activate(self):
        if not self.entries:
            return None
        entry = self.entries[self.selected]
        if entry.is_dir():
            self.navigate(entry)
            return None
        return entry

    def metadata(self):
        if not self.entries:
            return 'Empty directory'
        p = self.entries[self.selected]
        s = p.lstat()
        try:
            owner = pwd.getpwuid(s.st_uid).pw_name
        except KeyError:
            owner = str(s.st_uid)
        return f'{stat.filemode(s.st_mode)} {owner} {s.st_size} bytes {datetime.fromtimestamp(s.st_mtime):%Y-%m-%d %H:%M}'


def preview(path, limit=16384):
    # Never block on devices, sockets, FIFOs, or potentially infinite streams.
    if not stat.S_ISREG(path.stat().st_mode):
        return ['Preview is available for regular files only.']
    with path.open('rb') as stream:
        data = stream.read(limit)
    if b'\x00' in data:
        return ['Binary file; open it with an appropriate shell tool.']
    lines = data.decode('utf-8', errors='replace').splitlines()
    if len(data) == limit:
        lines.append('[Preview limited to 16 KiB]')
    return lines or ['[Empty file]']
