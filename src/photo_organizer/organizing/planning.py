"""Freeze full-scope memberships and source identities before applying actions."""

import datetime
import json
import os
import time
import uuid
from pathlib import Path

from photo_organizer.organizing.grouping import compile_levels, paths, selected_summary
from photo_organizer.search.query import select
from photo_organizer.storage.catalog import connect, report, writer_lock
from photo_organizer.storage.filesystem import relative_parts

MODES = {"album", "copy", "compress"}


def plan(state, spec, target=None, mode="album"):
    start = time.perf_counter()
    if mode not in MODES:
        raise ValueError("unsupported output mode")
    if not isinstance(spec, dict) or set(spec) - {
        "filter",
        "group_by",
        "groups",
        "quality",
        "long_edge",
        "result_set_id",
        "accept_candidates",
        "levels",
        "overlap",
        "group_spec_id",
        "name_template",
        "max_bytes",
        "date_basis",
    }:
        raise ValueError("invalid plan spec")
    if mode != "compress" and any(k in spec for k in ("quality", "long_edge", "max_bytes")):
        raise ValueError(
            "quality, long_edge and max_bytes require compress mode; copy preserves original bytes"
        )
    if mode == "compress":
        if type(spec.get("quality", 82)) is not int or not 1 <= spec.get("quality", 82) <= 95:
            raise ValueError("invalid JPEG quality")
        if (
            type(spec.get("long_edge", 1600)) is not int
            or not 64 <= spec.get("long_edge", 1600) <= 8192
        ):
            raise ValueError("invalid long edge")
    if "max_bytes" in spec and (
        mode != "compress" or type(spec["max_bytes"]) is not int or spec["max_bytes"] < 1024
    ):
        raise ValueError("max_bytes requires compress and at least 1024 bytes")
    date_basis = spec.get("date_basis", "capture")
    if date_basis not in ("capture", "import", "modified"):
        raise ValueError("invalid date_basis")
    with writer_lock(state), connect(state) as c:
        if mode != "album":
            if not target:
                raise ValueError("destination required")
            target = Path(os.path.abspath(target))
            for row in c.execute("SELECT DISTINCT root FROM files"):
                source = Path(row[0])
                if target == source or source in target.parents or target in source.parents:
                    raise ValueError("source/destination overlap")
        if spec.get("result_set_id"):
            if "filter" in spec:
                raise ValueError(
                    "refine the result set before planning; do not mix filter and result_set_id"
                )
            from photo_organizer.search.results import select_snapshot

            items = select_snapshot(c, spec["result_set_id"], spec.get("accept_candidates") is True)
        else:
            items = select(c, spec.get("filter", {}))
        if date_basis != "capture":
            date_column = (
                "imported_at"
                if date_basis == "import"
                else "datetime(mtime_ns/1000000000,'unixepoch')"
            )
            items = [
                {
                    **dict(row),
                    "taken": c.execute(
                        "SELECT " + date_column + " FROM files WHERE id=?", (row["id"],)
                    ).fetchone()[0],
                }
                for row in items
            ]
        from photo_organizer.organizing.organization import filename, group_paths

        if spec.get("group_spec_id") and any(k in spec for k in ("levels", "group_by", "groups")):
            raise ValueError("group spec cannot be mixed with grouping rules")
        assigned = (
            group_paths(c, spec["group_spec_id"], spec.get("result_set_id"))
            if spec.get("group_spec_id")
            else None
        )
        levels = compile_levels(c, spec) if assigned is None else []
        plan_id = uuid.uuid4().hex
        actions = []
        counts = {}
        destinations = set()
        estimated_bytes = 0
        for sequence, row in enumerate(items, 1):
            for group in (
                assigned.get(row["id"], ["unclassified"])
                if assigned is not None
                else paths(row, levels)
            ):
                counts[group] = counts.get(group, 0) + 1
                estimated_bytes += c.execute(
                    "SELECT COALESCE(size,0) FROM files WHERE id=?", (row["id"],)
                ).fetchone()[0]
                suffix = ".jpg" if mode == "compress" else Path(row["path"]).suffix.lower()
                if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
                    suffix = ".image"
                name = filename(
                    spec.get("name_template", "{sequence}-{hash}"), row, group, sequence, suffix
                )
                relative = f"{group}/{name}"
                import unicodedata

                collision = unicodedata.normalize("NFC", relative).casefold()
                if collision in destinations:
                    raise ValueError("naming collision; include id or sequence in template")
                if len(relative.encode()) > 2048:
                    raise ValueError("destination path exceeds 2048 bytes")
                destinations.add(collision)
                relative_parts(relative)
                if mode != "album":
                    destination = target / relative
                    if destination.exists() or destination.is_symlink():
                        raise ValueError("destination already exists: " + relative)
                    for ancestor in (target, *destination.parents):
                        if ancestor.is_symlink() or (ancestor.exists() and not ancestor.is_dir()):
                            raise ValueError("destination ancestor is not a regular directory")
                actions.append(
                    (uuid.uuid4().hex, plan_id, row["id"], row["path"], row["hash"], relative)
                )
        with c:
            c.execute(
                "INSERT INTO plans VALUES(?,?,?,?,?)",
                (
                    plan_id,
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    json.dumps(spec, ensure_ascii=False),
                    str(target) if target else None,
                    mode,
                ),
            )
            c.executemany(
                "INSERT INTO actions(id,plan_id,file_id,source,hash,relative) VALUES(?,?,?,?,?,?)",
                actions,
            )
        return {
            "plan_id": plan_id,
            "selected": len(items),
            "memberships": len(actions),
            "selected_summary": selected_summary(items, date_basis),
            "estimated_source_bytes": estimated_bytes,
            "output_size_note": "copy preserves bytes; compression size is measured during execution",
            "groups": counts,
            "library": report(c),
            "mode": mode,
            "seconds": time.perf_counter() - start,
            "model_calls": 0,
        }
