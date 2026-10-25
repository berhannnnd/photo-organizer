"""Cross-process provider slots with foreground priority and crash-safe OS locks."""

import fcntl
import hashlib
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from photo_organizer.core.errors import CapabilityError
from photo_organizer.runtime.context import background, checkpoint


def _lock(file):
    try:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _waiting(root):
    for path in root.glob("waiting-*"):
        try:
            with path.open("r+") as file:
                if not _lock(file):
                    return True
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
    return False


def _available_slot(root, requested_limit):
    free = []
    active_limits = []
    try:
        for index in range(8):
            candidate = (root / ("slot-" + str(index))).open("a+")
            if _lock(candidate):
                free.append(candidate)
            else:
                candidate.seek(0)
                try:
                    active_limits.append(max(1, min(8, int(candidate.read()))))
                except ValueError:
                    active_limits.append(1)
                candidate.close()
        effective = min([requested_limit, *active_limits])
        if len(active_limits) >= effective or not free:
            return None
        slot = free.pop(0)
        slot.seek(0)
        slot.truncate()
        slot.write(str(requested_limit))
        slot.flush()
        return slot
    finally:
        for file in free:
            file.close()


@contextmanager
def provider_slot(config):
    # Endpoint-wide: separate roles sharing a service also share its capacity.
    identity = hashlib.sha256(config["endpoint"].rstrip("/").encode()).hexdigest()
    root = Path(tempfile.gettempdir()) / ("photo-provider-" + str(os.getuid())) / identity
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    limit = config.get("concurrency", 2)
    deadline = time.monotonic() + config.get("timeout", 90)
    ticket = None
    slot = None
    with (root / "admission").open("a+") as mutex:
        try:
            if not background():
                ticket_path = root / ("waiting-" + uuid.uuid4().hex)
                fcntl.flock(mutex, fcntl.LOCK_EX)
                ticket = ticket_path.open("x+")
                fcntl.flock(ticket, fcntl.LOCK_EX)
                fcntl.flock(mutex, fcntl.LOCK_UN)
            while slot is None:
                checkpoint()
                fcntl.flock(mutex, fcntl.LOCK_EX)
                try:
                    if not background() or not _waiting(root):
                        slot = _available_slot(root, limit)
                    if slot is not None and ticket is not None:
                        ticket_path.unlink(missing_ok=True)
                        ticket.close()
                        ticket = None
                finally:
                    fcntl.flock(mutex, fcntl.LOCK_UN)
                if slot is None:
                    if time.monotonic() >= deadline:
                        raise CapabilityError("provider_busy", "Provider admission timed out", True)
                    time.sleep(0.05)
            yield
        finally:
            if ticket is not None:
                with (root / "admission").open("a+") as cleanup:
                    fcntl.flock(cleanup, fcntl.LOCK_EX)
                    ticket_path.unlink(missing_ok=True)
                    ticket.close()
            if slot is not None:
                slot.close()
