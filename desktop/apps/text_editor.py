"""A small UTF-8 text editor with bounded reads and non-clobbering saves."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile


MAX_FILE_BYTES = 1024 * 1024


class FileChangedError(OSError):
    """The file on disk no longer matches the version opened by the editor."""


@dataclass(frozen=True)
class _Version:
    metadata: tuple
    digest: bytes


def _metadata(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_regular(path):
    # Nonblocking open prevents FIFOs from hanging; NOFOLLOW prevents a final
    # symlink introduced after resolution from redirecting this operation.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Only regular text files can be edited.')
        if before.st_size > MAX_FILE_BYTES:
            raise ValueError('Text files must be at most 1 MiB.')
        data = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('Text files must be at most 1 MiB.')
    if _metadata(before) != _metadata(after):
        raise FileChangedError('The file changed while being read; reopen it.')
    return data, after, _Version(_metadata(after), hashlib.sha256(data).digest())


class TextEditor:
    """Edit lines without losing trailing newlines or the file's LF/CRLF style.

    Cursor columns count Unicode code points, rather than terminal display
    cells. New files are created with mode 0600; existing permissions and
    ownership are retained. Read-only files can be opened but cannot be saved.
    """

    def __init__(self):
        self.lines = ['']
        self.row = 0
        self.column = 0
        self.path = None
        self.dirty = False
        self._newline = '\n'
        self._version = None

    @classmethod
    def open(cls, path):
        editor = cls()
        destination = Path(path).expanduser().resolve(strict=True)
        data, _, version = _read_regular(destination)
        try:
            content = data.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('This file is not valid UTF-8 text.') from error
        if any(ord(character) < 32 and character not in '\t\r\n'
               or ord(character) == 127 for character in content):
            raise ValueError('This appears to be a binary file; it cannot be edited.')
        if '\r\n' in content:
            if '\n' in content.replace('\r\n', ''):
                raise ValueError('Mixed LF and CRLF line endings are not supported.')
            editor._newline = '\r\n'
            content = content.replace('\r\n', '\n')
        if '\r' in content:
            raise ValueError('Only LF and CRLF line endings are supported.')
        editor.lines = content.split('\n')
        editor.path = destination
        editor._version = version
        return editor

    def _offset(self):
        return sum(len(line) + 1 for line in self.lines[:self.row]) + self.column

    def _set_offset(self, offset):
        for row, line in enumerate(self.lines):
            if offset <= len(line):
                self.row, self.column = row, offset
                return
            offset -= len(line) + 1
        self.row = len(self.lines) - 1
        self.column = len(self.lines[-1])

    def _bytes(self, lines=None):
        data = self._newline.join(self.lines if lines is None else lines).encode('utf-8')
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('Text files must be at most 1 MiB.')
        return data

    def insert(self, text):
        if not text:
            return
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        if any(ord(character) < 32 and character not in '\t\n'
               or ord(character) == 127 for character in text):
            raise ValueError('Only printable text, tabs and newlines can be inserted.')
        line = self.lines[self.row]
        inserted = (line[:self.column] + text + line[self.column:]).split('\n')
        candidate = self.lines[:self.row] + inserted + self.lines[self.row + 1:]
        self._bytes(candidate)
        offset = self._offset() + len(text)
        self.lines = candidate
        self._set_offset(offset)
        self.dirty = True

    def backspace(self):
        if self.column:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.column - 1] + line[self.column:]
            self.column -= 1
        elif self.row:
            self.column = len(self.lines[self.row - 1])
            self.lines[self.row - 1:self.row + 1] = [
                self.lines[self.row - 1] + self.lines[self.row]]
            self.row -= 1
        else:
            return
        self.dirty = True

    def delete(self):
        line = self.lines[self.row]
        if self.column < len(line):
            self.lines[self.row] = line[:self.column] + line[self.column + 1:]
        elif self.row < len(self.lines) - 1:
            self.lines[self.row:self.row + 2] = [line + self.lines[self.row + 1]]
        else:
            return
        self.dirty = True

    def move(self, dr=0, dc=0):
        self.row = max(0, min(len(self.lines) - 1, self.row + dr))
        self.column = min(self.column, len(self.lines[self.row]))
        if dc:
            length = sum(map(len, self.lines)) + len(self.lines) - 1
            self._set_offset(max(0, min(length, self._offset() + dc)))

    def home(self):
        self.column = 0

    def end(self):
        self.column = len(self.lines[self.row])

    def find(self, query):
        """Find the next exact match, advancing past the cursor and wrapping."""
        if not query:
            return False
        content = '\n'.join(self.lines)
        query = query.replace('\r\n', '\n')
        offset = content.find(query, self._offset() + 1)
        if offset < 0:
            offset = content.find(query)
        if offset < 0:
            return False
        self._set_offset(offset)
        return True

    def _unchanged_file(self, destination):
        try:
            _, info, version = _read_regular(destination)
        except (OSError, ValueError) as error:
            raise FileChangedError(
                'The file changed, moved or became unreadable; reopen it or save under a new name.') from error
        if version != self._version:
            raise FileChangedError(
                'The file changed outside the editor; reopen it or save under a new name.')
        if not info.st_mode & 0o222 or not os.access(destination, os.W_OK):
            raise PermissionError('This file is read-only; save under a new name.')
        return info

    def save(self, path=None):
        """Atomically save, refusing existing Save As files and disk conflicts."""
        if path is None and self.path is None:
            raise ValueError('Choose a file name before saving.')
        requested = Path(path if path is not None else self.path).expanduser()
        destination = requested.resolve(strict=False)
        same_file = self.path is not None and destination == self.path
        # A dangling symlink is still an existing destination, not a new file.
        if not same_file and (requested.is_symlink() or os.path.lexists(destination)):
            raise FileExistsError(f'The destination already exists: {requested}')
        data = self._bytes()
        previous = self._unchanged_file(destination) if same_file else None
        descriptor, temporary = tempfile.mkstemp(prefix='.ascii-editor-', dir=destination.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                if previous is not None:
                    created = os.fstat(stream.fileno())
                    if (created.st_uid, created.st_gid) != (previous.st_uid, previous.st_gid):
                        os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
                    os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode))
                os.fsync(stream.fileno())
            if same_file:
                self._unchanged_file(destination)
                os.replace(temporary, destination)
            else:
                # Hard-link creation is atomic and fails if another writer has
                # created the destination since our first check.
                os.link(temporary, destination)
                os.unlink(temporary)
            info = destination.stat(follow_symlinks=False)
            self._version = _Version(_metadata(info), hashlib.sha256(data).digest())
            self.path = destination
            self.dirty = False
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
