"""Persistent user-added application commands, without shell execution."""
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shlex
import stat
import tempfile
import uuid

MAX_FILE_BYTES = 1024 * 1024
MAX_APPS = 256
MAX_ARGUMENTS = 128
MAX_COMMAND_CHARS = 16384
_UNLOADED = object()


@dataclass(frozen=True)
class Application:
    id: str
    name: str
    command: tuple[str, ...]
    description: str = ''
    launch_mode: str = 'terminal'


@dataclass(frozen=True)
class _Snapshot:
    data: bytes
    identity: tuple[int, ...]
    mode: int


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid)


def _string(value, label, limit, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be text.')
    if not allow_empty and not value.strip():
        raise ValueError(f'{label} cannot be empty.')
    if len(value) > limit:
        raise ValueError(f'{label} is too long (maximum {limit} characters).')
    if any(not character.isprintable() for character in value):
        raise ValueError(f'{label} cannot contain control characters.')
    return value


def validate_install_command(command):
    """Validate a printable Bash command for review, without running it."""
    return _string(command, 'Download/install command', MAX_COMMAND_CHARS).strip()


def _launch_mode(value):
    if not isinstance(value, str) or value not in ('terminal', 'graphical'):
        raise ValueError('Launch mode must be terminal or graphical.')
    return value


def _application(record):
    if not isinstance(record, dict) or set(record) - {
            'id', 'name', 'command', 'description', 'launch_mode'}:
        raise ValueError('Apps catalog contains an invalid application record.')
    app_id = _string(record.get('id'), 'Application ID', 128)
    name = _string(record.get('name'), 'Application name', 128)
    description = _string(record.get('description', ''), 'Description', 1024, allow_empty=True)
    launch_mode = _launch_mode(record.get('launch_mode', 'terminal'))
    command = record.get('command')
    if not isinstance(command, (list, tuple)) or not 1 <= len(command) <= MAX_ARGUMENTS:
        raise ValueError(f'Command must contain 1 to {MAX_ARGUMENTS} arguments.')
    arguments = tuple(_string(argument, 'Command argument', 4096, allow_empty=index != 0)
                      for index, argument in enumerate(command))
    return Application(app_id, name, arguments, description, launch_mode)


def _records(entries):
    return [{'id': entry.id, 'name': entry.name, 'command': list(entry.command),
             'description': entry.description, 'launch_mode': entry.launch_mode}
            for entry in entries]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Apps catalog contains duplicate JSON fields.')
        result[key] = value
    return result


class AppCatalog:
    def __init__(self, path=None):
        if path is None:
            data_home = os.environ.get('XDG_DATA_HOME', '')
            base = Path(data_home) if os.path.isabs(data_home) else Path.home() / '.local/share'
            path = base / 'ascii-linux/apps.json'
        self.path = Path(path).expanduser().absolute()
        self.entries = []
        self._baseline = _UNLOADED

    def _read(self):
        try:
            before = self.path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Apps catalog must be a regular file.')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        with os.fdopen(os.open(self.path, flags), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if _identity(before) != _identity(opened) or not stat.S_ISREG(opened.st_mode):
                raise ValueError('Apps catalog changed while reading; reload it.')
            if opened.st_size > MAX_FILE_BYTES:
                raise ValueError('Apps catalog exceeds the 1 MiB size limit.')
            data = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('Apps catalog exceeds the 1 MiB size limit.')
        if _identity(opened) != _identity(after) or _identity(after) != _identity(self.path.lstat()):
            raise ValueError('Apps catalog changed while reading; reload it.')
        return _Snapshot(data, _identity(after), stat.S_IMODE(after.st_mode))

    def load(self):
        snapshot = self._read()
        if snapshot is None:
            entries = []
        else:
            try:
                records = json.loads(snapshot.data.decode('utf-8'), object_pairs_hook=_unique_object)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
                raise ValueError('Apps catalog is not valid UTF-8 JSON; existing data was kept.') from error
            if not isinstance(records, list) or len(records) > MAX_APPS:
                raise ValueError(f'Apps catalog must be a list of at most {MAX_APPS} applications.')
            entries = [_application(record) for record in records]
            if len({entry.id for entry in entries}) != len(entries):
                raise ValueError('Apps catalog contains duplicate application IDs.')
        self.entries = entries
        self._baseline = snapshot
        return self.entries

    def _ensure_loaded(self):
        if self._baseline is _UNLOADED:
            self.load()

    def _check_current(self):
        current = self._read()
        if current != self._baseline:
            raise ValueError('Apps catalog changed outside the desktop; reload before changing it.')
        return current

    def _encode(self, entries):
        if len(entries) > MAX_APPS:
            raise ValueError(f'Apps catalog supports at most {MAX_APPS} applications.')
        records = _records(entries)
        # Validate the complete prospective file before changing any existing data.
        validated = [_application(record) for record in records]
        if len({entry.id for entry in validated}) != len(validated):
            raise ValueError('Apps catalog contains duplicate application IDs.')
        data = (json.dumps(records, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('Apps catalog exceeds the 1 MiB size limit.')
        return validated, data

    def _save(self, entries):
        validated, data = self._encode(entries)
        current = self._check_current()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.ascii-apps-', dir=self.path.parent,
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
                    # Publish a new catalog without replacing a concurrent creator.
                    os.link(temporary, self.path)
                except FileExistsError as error:
                    raise ValueError('Apps catalog was created outside the desktop; reload it.') from error
            else:
                os.replace(temporary, self.path)
            temporary.unlink(missing_ok=True)
            saved = self._read()
            if saved is None or saved.data != data:
                raise ValueError('Apps catalog changed after saving; reload it.')
            self.entries, self._baseline = validated, saved
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def prepare_add(self, name, command, description='', launch_mode='terminal'):
        """Validate a prospective launcher without writing it to the catalog."""
        self._ensure_loaded()
        name = _string(name, 'Application name', 128).strip()
        command = _string(command, 'Command', MAX_COMMAND_CHARS)
        description = _string(description, 'Description', 1024, allow_empty=True)
        try:
            arguments = shlex.split(command)
        except ValueError as error:
            raise ValueError('Command has unmatched quotes or an incomplete escape.') from error
        if not arguments:
            raise ValueError('Command cannot be empty.')
        _string(arguments[0], 'Executable', 4096)
        try:
            if arguments[0].startswith('~'):
                arguments[0] = str(Path(arguments[0]).expanduser())
        except RuntimeError as error:
            raise ValueError('Cannot expand the executable path: unknown home directory.') from error
        entry = _application({'id': uuid.uuid4().hex, 'name': name, 'command': arguments,
                              'description': description, 'launch_mode': launch_mode})
        self._check_current()
        if len(self.entries) >= MAX_APPS:
            raise ValueError(f'Apps catalog supports at most {MAX_APPS} applications.')
        self._encode(self.entries + [entry])
        return entry

    def commit_add(self, entry):
        """Save a prepared launcher after rechecking its data and catalog state."""
        self._ensure_loaded()
        if not isinstance(entry, Application):
            raise ValueError('Prepared application must be an Application record.')
        validated = _application({'id': entry.id, 'name': entry.name,
                                  'command': entry.command, 'description': entry.description,
                                  'launch_mode': entry.launch_mode})
        self._check_current()
        if any(existing.id == validated.id for existing in self.entries):
            raise ValueError('Application ID already exists in the catalog.')
        if len(self.entries) >= MAX_APPS:
            raise ValueError(f'Apps catalog supports at most {MAX_APPS} applications.')
        self._save(self.entries + [validated])
        return validated

    def add(self, name, command, description='', launch_mode='terminal'):
        return self.commit_add(self.prepare_add(name, command, description, launch_mode))

    def set_launch_mode(self, app_id, launch_mode):
        """Change one launcher's mode without replacing its command or identity."""
        self._ensure_loaded()
        _string(app_id, 'Application ID', 128)
        launch_mode = _launch_mode(launch_mode)
        self._check_current()
        for index, entry in enumerate(self.entries):
            if entry.id == app_id:
                updated = replace(entry, launch_mode=launch_mode)
                entries = self.entries.copy()
                entries[index] = updated
                self._save(entries)
                return updated
        raise ValueError('Application is no longer in the catalog; reload it.')

    def remove(self, app_id):
        self._ensure_loaded()
        _string(app_id, 'Application ID', 128)
        entries = [entry for entry in self.entries if entry.id != app_id]
        if len(entries) == len(self.entries):
            raise ValueError('Application is no longer in the catalog; reload it.')
        self._save(entries)
