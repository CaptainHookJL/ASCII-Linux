"""A small UTF-8 text editor with bounded reads and non-clobbering saves."""
from dataclasses import dataclass
from collections import deque
import hashlib
import os
from pathlib import Path
import stat
import tempfile


MAX_FILE_BYTES = 1024 * 1024
MAX_HISTORY_SNAPSHOTS = 100
MAX_HISTORY_BYTES = 8 * 1024 * 1024


class FileChangedError(OSError):
    """The file on disk no longer matches the version opened by the editor."""


@dataclass(frozen=True)
class _Version:
    metadata: tuple
    digest: bytes


@dataclass(frozen=True)
class _Snapshot:
    content: str
    row: int
    column: int
    utf8_bytes: int


@dataclass(frozen=True)
class _Change:
    before: _Snapshot
    after: _Snapshot

    @property
    def utf8_bytes(self):
        return self.before.utf8_bytes + self.after.utf8_bytes


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

    Undo/redo retains at most 100 before/after snapshots (50 edits), with at
    most 8 MiB of UTF-8 snapshot content in total. The oldest edits are dropped
    when either limit is reached; a 1 MiB document still has room for four
    edits. Moving the cursor, searching and saving do not add history. Saving
    preserves history and marks the saved content as the clean baseline.
    """

    def __init__(self):
        self.lines = ['']
        self.row = 0
        self.column = 0
        self.path = None
        self.dirty = False
        self._newline = '\n'
        self._version = None
        self._saved_content = ''
        self._undo = deque()
        self._redo = []
        self._history_bytes = 0

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
        editor._saved_content = content
        return editor

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def _snapshot(self, lines=None, row=None, column=None):
        content = '\n'.join(self.lines if lines is None else lines)
        return _Snapshot(content, self.row if row is None else row,
                         self.column if column is None else column,
                         len(content.encode('utf-8')))

    def _apply_edit(self, lines, row, column):
        # Build and validate the complete change before touching the document
        # or its history. Invalid/oversize input cannot invalidate redo.
        self._bytes(lines)
        change = _Change(self._snapshot(), self._snapshot(lines, row, column))
        self._history_bytes -= sum(item.utf8_bytes for item in self._redo)
        self._redo.clear()
        self._undo.append(change)
        self._history_bytes += change.utf8_bytes
        while (len(self._undo) * 2 > MAX_HISTORY_SNAPSHOTS
               or self._history_bytes > MAX_HISTORY_BYTES):
            self._history_bytes -= self._undo.popleft().utf8_bytes
        self.lines = lines
        self.row, self.column = row, column
        self.dirty = change.after.content != self._saved_content

    def _restore(self, snapshot):
        self.lines = snapshot.content.split('\n')
        self.row, self.column = snapshot.row, snapshot.column
        self.dirty = snapshot.content != self._saved_content

    def undo(self):
        """Restore the content and cursor before the last edit, if available."""
        if not self._undo:
            return False
        change = self._undo[-1]
        self._restore(change.before)
        self._redo.append(self._undo.pop())
        return True

    def redo(self):
        """Restore the content and cursor after the last undone edit."""
        if not self._redo:
            return False
        change = self._redo[-1]
        self._restore(change.after)
        self._undo.append(self._redo.pop())
        return True

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
        row = self.row + len(inserted) - 1
        column = (self.column + len(text) if len(inserted) == 1
                  else len(text.rsplit('\n', 1)[1]))
        self._apply_edit(candidate, row, column)

    def backspace(self):
        candidate = self.lines.copy()
        if self.column:
            line = self.lines[self.row]
            candidate[self.row] = line[:self.column - 1] + line[self.column:]
            row, column = self.row, self.column - 1
        elif self.row:
            column = len(self.lines[self.row - 1])
            candidate[self.row - 1:self.row + 1] = [
                self.lines[self.row - 1] + self.lines[self.row]]
            row = self.row - 1
        else:
            return
        self._apply_edit(candidate, row, column)

    def delete(self):
        line = self.lines[self.row]
        candidate = self.lines.copy()
        if self.column < len(line):
            candidate[self.row] = line[:self.column] + line[self.column + 1:]
        elif self.row < len(self.lines) - 1:
            candidate[self.row:self.row + 2] = [line + self.lines[self.row + 1]]
        else:
            return
        self._apply_edit(candidate, self.row, self.column)

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
            self._saved_content = '\n'.join(self.lines)
            self.dirty = False
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
