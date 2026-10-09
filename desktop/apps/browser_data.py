"""User bookmarks with bounded reads and atomic, conflict-aware writes."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlsplit

from .web_browser import normalize_url

MAX_FILE_BYTES = 1024 * 1024
MAX_BOOKMARKS = 256
MAX_NAME_CHARS = 256
MAX_URL_CHARS = 8192
_UNLOADED = object()


@dataclass(frozen=True)
class Bookmark:
    name: str
    url: str


@dataclass(frozen=True)
class _Snapshot:
    data: bytes
    identity: tuple[int, ...]
    mode: int


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid)


def _text(value, label, limit):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text.')
    if len(value) > limit:
        raise ValueError(f'{label} is too long (maximum {limit} characters).')
    if any(not character.isprintable() for character in value):
        raise ValueError(f'{label} cannot contain control characters.')
    return value


def _url(value, *, stored=False):
    value = _text(value, 'Bookmark URL', MAX_URL_CHARS)
    if stored and urlsplit(value).scheme.lower() not in ('http', 'https'):
        raise ValueError('Stored bookmark URLs must use HTTP or HTTPS.')
    value = normalize_url(value)
    # Percent encoding can expand an otherwise short international URL.
    return _text(value, 'Bookmark URL', MAX_URL_CHARS)


def _bookmark(record):
    if not isinstance(record, dict) or set(record) != {'name', 'url'}:
        raise ValueError('Bookmarks contain an invalid record.')
    name = _text(record['name'], 'Bookmark name', MAX_NAME_CHARS)
    return Bookmark(name, _url(record['url'], stored=True))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Bookmarks contain duplicate JSON fields.')
        result[key] = value
    return result


class BookmarkStore:
    def __init__(self, path=None):
        if path is None:
            data_home = os.environ.get('XDG_DATA_HOME', '')
            base = Path(data_home) if os.path.isabs(data_home) else Path.home() / '.local/share'
            path = base / 'ascii-linux/browser-bookmarks.json'
        self.path = Path(path).expanduser().absolute()
        self.entries = []
        self._baseline = _UNLOADED

    def _read(self):
        try:
            before = self.path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Bookmarks must be a regular file.')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        with os.fdopen(os.open(self.path, flags), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if _identity(before) != _identity(opened) or not stat.S_ISREG(opened.st_mode):
                raise ValueError('Bookmarks changed while reading; reload them.')
            if opened.st_size > MAX_FILE_BYTES:
                raise ValueError('Bookmarks exceed the 1 MiB size limit.')
            data = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('Bookmarks exceed the 1 MiB size limit.')
        if _identity(opened) != _identity(after) or _identity(after) != _identity(self.path.lstat()):
            raise ValueError('Bookmarks changed while reading; reload them.')
        return _Snapshot(data, _identity(after), stat.S_IMODE(after.st_mode))

    def load(self):
        snapshot = self._read()
        if snapshot is None:
            entries = []
        else:
            try:
                records = json.loads(snapshot.data.decode('utf-8'), object_pairs_hook=_unique_object)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
                raise ValueError('Bookmarks are not valid UTF-8 JSON; existing data was kept.') from error
            if not isinstance(records, list) or len(records) > MAX_BOOKMARKS:
                raise ValueError(f'Bookmarks must be a list of at most {MAX_BOOKMARKS} entries.')
            entries = [_bookmark(record) for record in records]
            if len({entry.url for entry in entries}) != len(entries):
                raise ValueError('Bookmarks contain duplicate URLs.')
        self.entries, self._baseline = entries, snapshot
        return self.entries

    def _ensure_loaded(self):
        if self._baseline is _UNLOADED:
            self.load()

    def _check_current(self):
        current = self._read()
        if current != self._baseline:
            raise ValueError('Bookmarks changed outside the desktop; reload before changing them.')
        return current

    def _encode(self, entries):
        if len(entries) > MAX_BOOKMARKS:
            raise ValueError(f'Bookmarks support at most {MAX_BOOKMARKS} entries.')
        records = [{'name': entry.name, 'url': entry.url} for entry in entries]
        validated = [_bookmark(record) for record in records]
        if len({entry.url for entry in validated}) != len(validated):
            raise ValueError('Bookmarks contain duplicate URLs.')
        data = (json.dumps(records, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('Bookmarks exceed the 1 MiB size limit.')
        return validated, data

    def _save(self, entries):
        validated, data = self._encode(entries)
        current = self._check_current()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.ascii-bookmarks-', dir=self.path.parent,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                if current is not None:
                    os.fchmod(stream.fileno(), current.mode)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_current()
            if current is None:
                try:
                    os.link(temporary, self.path)
                except FileExistsError as error:
                    raise ValueError('Bookmarks were created outside the desktop; reload them.') from error
            else:
                os.replace(temporary, self.path)
            temporary.unlink(missing_ok=True)
            saved = self._read()
            if saved is None or saved.data != data:
                raise ValueError('Bookmarks changed after saving; reload them.')
            self.entries, self._baseline = validated, saved
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def add(self, name, url):
        """Save a bookmark; bookmarking an existing URL keeps its original name."""
        self._ensure_loaded()
        name = _text(name, 'Bookmark name', MAX_NAME_CHARS).strip()
        url = _url(url)
        self._check_current()
        for entry in self.entries:
            if entry.url == url:
                return entry
        entry = Bookmark(name, url)
        self._save(self.entries + [entry])
        return entry

    def remove(self, url):
        self._ensure_loaded()
        url = _url(url)
        self._check_current()
        entries = [entry for entry in self.entries if entry.url != url]
        if len(entries) == len(self.entries):
            raise ValueError('Bookmark is no longer saved; reload bookmarks.')
        self._save(entries)
