"""Per-execution admission hooks shared by local and HTTP capability adapters."""

from contextlib import contextmanager
from contextvars import ContextVar

_BACKGROUND = ContextVar("photo_background", default=False)
_ADMISSION = ContextVar("photo_admission", default=None)
_CHECKPOINT = ContextVar("photo_checkpoint", default=None)
_COMMIT = ContextVar("photo_commit", default=None)


@contextmanager
def execution_context(*, background=False, admission=None, checkpoint=None, commit=None):
    tokens = (
        _BACKGROUND.set(background),
        _ADMISSION.set(admission),
        _CHECKPOINT.set(checkpoint),
        _COMMIT.set(commit),
    )
    try:
        yield
    finally:
        for variable, token in zip((_BACKGROUND, _ADMISSION, _CHECKPOINT, _COMMIT), tokens):
            variable.reset(token)


def background():
    return _BACKGROUND.get()


def checkpoint():
    callback = _CHECKPOINT.get()
    if callback:
        callback()


def admit(remote=True):
    checkpoint()
    callback = _ADMISSION.get()
    if callback:
        callback(remote)


def commit_guard(connection):
    """Validate bound job configuration under the same write transaction as its result."""
    callback = _COMMIT.get()
    if callback:
        connection.execute("BEGIN IMMEDIATE")
        callback(connection)
