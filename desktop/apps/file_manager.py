"""File browsing and safe, noninteractive filesystem operations."""
import ctypes
from datetime import datetime
import errno
import os
from pathlib import Path
import pwd
import shutil
import stat
import tempfile


class _Progress:
    def __init__(self, callback, total):
        self.callback = callback
        self.total = total
        self.done = 0
        self.report()

    def report(self):
        if self.callback:
            self.callback(self.done, self.total)

    def advance(self, count):
        self.done += count
        self.total = max(self.total, self.done)
        self.report()

    def finish(self):
        # A file can change size while being copied; report actual bytes at completion.
        self.total = self.done
        self.report()


def _exists(path):
    """Unlike Path.exists(), include dangling symbolic links."""
    return os.path.lexists(path)


def _require_absent(path):
    if _exists(path):
        raise FileExistsError(errno.EEXIST, 'Destination already exists; choose another name', str(path))


def _rename_no_replace(source, destination):
    """Publish or move without replacing an entry, even if one appears mid-operation.

    Linux renameat2 also protects directories against races. The link/unlink fallback
    supports files and symlinks on systems without that API; directory moves require
    a filesystem with renameat2 support.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is not None:
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
            return
        error = ctypes.get_errno()
        if error not in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
            raise OSError(error, os.strerror(error), str(destination))
    if stat.S_ISDIR(source.lstat().st_mode):
        raise OSError(errno.ENOTSUP, 'Safe directory rename is unavailable on this filesystem', str(destination))
    os.link(source, destination, follow_symlinks=False)
    try:
        source.unlink()
    except OSError:
        destination.unlink()
        raise


def _discard_stage(stage):
    # Copied folders can be read-only. Only loosen our private staging folders
    # so failure cleanup remains possible without changing the original tree.
    for parent, directories, _files in os.walk(stage, followlinks=False):
        os.chmod(parent, stat.S_IMODE(os.stat(parent).st_mode) | 0o700)
        for name in directories:
            child = Path(parent) / name
            info = child.lstat()
            if stat.S_ISDIR(info.st_mode):
                os.chmod(child, stat.S_IMODE(info.st_mode) | 0o700)
    shutil.rmtree(stage)


def _copy_size(path):
    """Reject special files before copying anything; do not traverse symlinks."""
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        return 0
    if stat.S_ISREG(mode):
        return path.lstat().st_size
    if stat.S_ISDIR(mode):
        return sum(_copy_size(child) for child in path.iterdir())
    raise ValueError(f'Cannot copy special file: {path}. Use a shell tool for devices, sockets or pipes.')


def _delete_size(path):
    info = path.lstat()
    if stat.S_ISDIR(info.st_mode):
        return sum(_delete_size(child) for child in path.iterdir())
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


def _copy_file(source, destination, progress):
    # O_NONBLOCK and fstat protect against a file being replaced by a pipe/device.
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, 'rb') as reader:
        info = os.fstat(reader.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f'Cannot copy nonregular file: {source}')
        with open(destination, 'xb') as writer:
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
                progress.advance(len(chunk))
        os.chmod(destination, stat.S_IMODE(info.st_mode))
        os.utime(destination, ns=(info.st_atime_ns, info.st_mtime_ns))
    return str(destination)


def _copy_node(source, destination, progress):
    mode = source.lstat().st_mode
    if stat.S_ISLNK(mode):
        os.symlink(os.readlink(source), destination)
        shutil.copystat(source, destination, follow_symlinks=False)
    elif stat.S_ISDIR(mode):
        shutil.copytree(source, destination, symlinks=True,
                        copy_function=lambda src, dst: _copy_file(src, dst, progress))
    elif stat.S_ISREG(mode):
        _copy_file(source, destination, progress)
    else:
        raise ValueError(f'Cannot copy special file: {source}')


def _remove_at(parent_fd, name, progress):
    """Use directory descriptors so deletion never follows a symbolic link."""
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        try:
            with os.scandir(descriptor) as children:
                names = [entry.name for entry in children]
            for child in names:
                _remove_at(descriptor, child, progress)
        finally:
            os.close(descriptor)
        os.rmdir(name, dir_fd=parent_fd)
    else:
        os.unlink(name, dir_fd=parent_fd)
        if stat.S_ISREG(info.st_mode):
            progress.advance(info.st_size)


def _delete_node(path, progress):
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _remove_at(descriptor, path.name, progress)
    finally:
        os.close(descriptor)


class FileManager:
    def __init__(self, path=None):
        self.path = Path(path or Path.home()).resolve()
        self.hidden = False
        self.query = ''
        self.selected = 0
        self.entries = []
        self.refresh()

    @property
    def selected_entry(self):
        return self.entries[self.selected] if 0 <= self.selected < len(self.entries) else None

    def refresh(self):
        query = self.query.casefold()
        entries = [p for p in self.path.iterdir()
                   if (self.hidden or not p.name.startswith('.')) and query in p.name.casefold()]
        self.entries = sorted(entries, key=lambda p: (not p.is_dir(), p.name.casefold()))
        self.selected = min(self.selected, max(0, len(self.entries) - 1))

    def set_query(self, query):
        self.query = str(query)
        self.selected = 0
        self.refresh()

    def _refresh_select(self, path=None):
        self.refresh()
        if path in self.entries:
            self.selected = self.entries.index(path)

    def _selection(self):
        entry = self.selected_entry
        if entry is None:
            raise ValueError('Select a file or folder first.')
        return entry

    @staticmethod
    def _basename(name):
        name = os.fspath(name)
        if not isinstance(name, str) or name in ('', '.', '..') or '/' in name or '\x00' in name:
            raise ValueError("Enter a single file or folder name; paths, '.' and '..' are not allowed.")
        return name

    def _destination(self, source, destination):
        if not os.fspath(destination):
            raise ValueError('Enter a destination path.')
        target = Path(destination).expanduser()
        if not target.is_absolute():
            target = self.path / target
        if target.is_dir():
            target /= source.name
        _require_absent(target)
        if stat.S_ISDIR(source.lstat().st_mode):
            real_source = source.resolve()
            real_target = target.resolve()
            if real_target == real_source or real_source in real_target.parents:
                raise ValueError('A folder cannot be copied or moved into itself.')
        if not target.parent.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, 'Destination parent must be an existing folder', str(target.parent))
        return target

    def mkdir(self, name):
        target = self.path / self._basename(name)
        target.mkdir()
        self._refresh_select(target)
        return target

    def rename_to(self, destination):
        source = self._selection()
        target = self.path / self._basename(destination)
        _require_absent(target)
        _rename_no_replace(source, target)
        self._refresh_select(target)
        return target

    @staticmethod
    def _copy_to(source, target, progress):
        # Stage alongside the destination, then publish atomically. A failed copy
        # leaves the original untouched and no incomplete user-visible destination.
        stage = Path(tempfile.mkdtemp(prefix='.ascii-copy-', dir=target.parent))
        try:
            staged = stage / 'entry'
            _copy_node(source, staged, progress)
            progress.finish()
            _rename_no_replace(staged, target)
        finally:
            _discard_stage(stage)

    def copy_to(self, destination, progress=None):
        source = self._selection()
        target = self._destination(source, destination)
        tracker = _Progress(progress, _copy_size(source))
        self._copy_to(source, target, tracker)
        self._refresh_select(target)
        return target

    def move_to(self, destination, progress=None):
        source = self._selection()
        target = self._destination(source, destination)
        # A same-filesystem move only changes directory entries. It does not
        # require reading children or treating special files as copyable streams.
        tracker = _Progress(progress, 0)
        try:
            _rename_no_replace(source, target)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            total = _copy_size(source)
            tracker = _Progress(progress, total)
            self._copy_to(source, target, tracker)
            try:
                _delete_node(source, _Progress(None, total))
            except OSError as remove_error:
                self._refresh_select(target)
                raise OSError(remove_error.errno,
                              f'Copy retained at {target}; removing the original failed: {remove_error}',
                              str(source)) from remove_error
        else:
            try:
                tracker.finish()
            finally:
                self._refresh_select(target)
            return target
        self._refresh_select(target)
        return target

    def delete_selected(self, progress=None):
        source = self._selection()
        tracker = _Progress(progress, _delete_size(source))
        try:
            _delete_node(source, tracker)
            tracker.finish()
        finally:
            # Failed recursive deletions may have removed some children.
            self.refresh()

    def move(self, delta):
        self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))

    def parent(self):
        self.navigate(self.path.parent)

    def navigate(self, path):
        old, old_query = self.path, self.query
        self.path = Path(path).resolve()
        self.query = ''
        try:
            self.refresh()
        except OSError:
            self.path, self.query = old, old_query
            raise
        self.selected = 0

    def activate(self):
        entry = self.selected_entry
        if entry is None:
            return None
        if entry.is_dir():
            self.navigate(entry)
            return None
        return entry

    def metadata(self):
        p = self.selected_entry
        if p is None:
            return 'Empty directory'
        s = p.lstat()
        try:
            owner = pwd.getpwuid(s.st_uid).pw_name
        except KeyError:
            owner = str(s.st_uid)
        return f'{stat.filemode(s.st_mode)} {owner} {s.st_size} bytes {datetime.fromtimestamp(s.st_mtime):%Y-%m-%d %H:%M}'


def preview(path, limit=16384):
    # Resolve an existing link, then refuse links introduced during the open.
    # O_NONBLOCK and fstat also cover a regular file being replaced by a FIFO.
    path = Path(path).resolve(strict=True)
    if not stat.S_ISREG(path.stat().st_mode):
        return ['Preview is available for regular files only.']
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            return ['Preview is available for regular files only.']
        data = stream.read(limit)
    if b'\x00' in data:
        return ['Binary file; open it with an appropriate shell tool.']
    lines = data.decode('utf-8', errors='replace').splitlines()
    if len(data) == limit:
        lines.append('[Preview limited to 16 KiB]')
    return lines or ['[Empty file]']
