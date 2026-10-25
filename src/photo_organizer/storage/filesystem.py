"""No-follow file IO and bounded relative paths for local sources and exports (POSIX)."""

import contextlib
import hashlib
import os
import stat
from pathlib import Path


def digest_file(file):
    h = hashlib.sha256()
    while chunk := file.read(1024 * 1024):
        h.update(chunk)
    return h.hexdigest()


@contextlib.contextmanager
def directory(path, create=False):
    path = Path(os.path.abspath(path))
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def read_source(path):
    path = Path(path)
    with directory(path.parent) as fd:
        handle = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(handle, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError("source must be a regular file")
            yield f


def digest(path):
    with read_source(path) as f:
        return digest_file(f)


def relative_parts(value):
    p = Path(value)
    if p.is_absolute() or not p.parts or any(x in ("..", ".") for x in p.parts) or "\\" in value:
        raise ValueError("unsafe relative destination")
    return p.parts
