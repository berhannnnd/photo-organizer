"""Append-only user metadata corrections; machine observations remain intact."""

import datetime
import json
import math
import uuid

from photo_organizer.core.paging import page, validate
from photo_organizer.search.selection import members, now
from photo_organizer.storage.catalog import connect, writer_lock

FIELDS = {"taken", "category", "caption", "latitude", "longitude", "tags", "notes"}


def correct(state, result_id, records, reason=""):
    """Record user-authorized metadata corrections; null resets a field to machine evidence."""
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError("provide 1..100 correction records")
    if not isinstance(reason, str) or len(reason) > 2000:
        raise ValueError("invalid correction reason")
    with writer_lock(state), connect(state) as c:
        scope = {
            r["file_id"]: r
            for r in members(
                c, result_id, ("matched", "candidate", "unknown", "unanalyzed", "not_matched")
            )
        }
        updates = []
        for row in records:
            if (
                not isinstance(row, dict)
                or row.get("file_id") not in scope
                or row.get("hash") != scope[row["file_id"]]["hash"]
            ):
                raise ValueError("out-of-scope or stale correction")
            changes = row.get("changes")
            if not isinstance(changes, dict) or not changes or set(changes) - FIELDS:
                raise ValueError("invalid correction fields")
            for field, value in changes.items():
                if value is not None:
                    if field == "taken":
                        if not isinstance(value, str):
                            raise ValueError("taken must be ISO date/time")
                        datetime.datetime.fromisoformat(value)
                    elif field in ("latitude", "longitude"):
                        bound = 90 if field == "latitude" else 180
                        if (
                            type(value) not in (int, float)
                            or not math.isfinite(value)
                            or abs(value) > bound
                        ):
                            raise ValueError("invalid coordinate")
                    elif field == "tags":
                        if (
                            not isinstance(value, list)
                            or len(value) > 100
                            or any(
                                not isinstance(t, str) or not 1 <= len(t.strip()) <= 200
                                for t in value
                            )
                        ):
                            raise ValueError("invalid tags")
                        value = sorted({t.strip().casefold() for t in value})
                    elif not isinstance(value, str) or not 1 <= len(value) <= 4000:
                        raise ValueError("invalid text correction")
                updates.append(
                    (
                        uuid.uuid4().hex,
                        row["hash"],
                        field,
                        json.dumps(value, ensure_ascii=False),
                        "",
                        json.dumps({"kind": "user", "reason": reason}),
                        now(),
                    )
                )
        c.executemany("INSERT INTO corrections VALUES(?,?,?,?,?,?,?)", updates)
    return {"saved": len(updates), "source": "user", "machine_observations_preserved": True}


def history(state, result_id, file_id, limit=50, offset=0):
    validate(limit, offset)
    with connect(state) as c:
        scope = {
            r["file_id"]: r
            for r in members(
                c, result_id, ("matched", "candidate", "unknown", "unanalyzed", "not_matched")
            )
        }
        if file_id not in scope:
            raise ValueError("file outside result scope")
        sha = scope[file_id]["hash"]
        total = c.execute("SELECT count(*) FROM corrections WHERE hash=?", (sha,)).fetchone()[0]
        rows = [
            {**dict(r), "value": json.loads(r["value"]), "source": json.loads(r["source"])}
            for r in c.execute(
                "SELECT * FROM corrections WHERE hash=? ORDER BY created DESC,id DESC LIMIT ? OFFSET ?",
                (sha, limit, offset),
            )
        ]
        return {"hash": sha, **page(rows, total, limit, offset)}
