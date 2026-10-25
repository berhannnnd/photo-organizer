"""One-item job actions. Domain implementations own observations and file safety."""

import base64
import json

from photo_organizer.capabilities.registry import get_config, vision
from photo_organizer.runtime.context import checkpoint, commit_guard
from photo_organizer.storage.catalog import connect


def execute(state, operation, spec, row):
    if operation == "scan":
        from photo_organizer.library.lifecycle import synchronize

        return synchronize(state, spec["root"], verify=spec.get("verify", False))
    if operation == "apply":
        from photo_organizer.organizing.execution import apply

        result = apply(state, spec["plan_id"], action_ids=[row["action_id"]], finalize=False)
        if result["errors"]:
            raise ValueError(result["errors"][0]["error"])
        return result
    # Bind each staged item to the current frozen scope before spending or writing.
    with connect(state) as c:
        current = c.execute(
            "SELECT hash,present,error FROM files WHERE id=?", (row["file_id"],)
        ).fetchone()
        if (
            not current
            or current["hash"] != row["hash"]
            or not current["present"]
            or current["error"]
        ):
            raise ValueError("stale or unavailable job input")
        asset = dict(c.execute("SELECT * FROM assets WHERE hash=?", (row["hash"],)).fetchone())
    if operation in ("quality", "ocr"):
        from photo_organizer.vision.analysis_tools import analyze_one

        return analyze_one(state, row, operation)
    if operation == "faces":
        from photo_organizer.vision.people import index_one

        return index_one(state, spec["result_id"], row)
    if operation == "embed":
        from pathlib import Path

        from photo_organizer.capabilities.adapters.encoding import Encoder
        from photo_organizer.search.embeddings import initialize, register

        encoder = Encoder(get_config(state, "image_text"))
        with connect(state) as c:
            initialize(c)
            if c.execute(
                "SELECT 1 FROM image_vectors WHERE space_id=? AND hash=?",
                (encoder.space, row["hash"]),
            ).fetchone():
                return {"cached": True}
        blob = encoder.encode(
            {"image": base64.b64encode(Path(asset["derivative"]).read_bytes()).decode()}
        )
        checkpoint()
        with connect(state) as c:
            commit_guard(c)
            register(c, encoder, blob)
            c.execute(
                "INSERT OR REPLACE INTO image_vectors VALUES(?,?,?)",
                (encoder.space, row["hash"], blob),
            )
        return {"space": encoder.space}
    provider = vision(state)
    if operation == "index":
        if asset["vision_state"] == "complete" and asset["vision_version"] == provider.version:
            return {"cached": True}
        label, metrics = provider.label(asset["derivative"])
        checkpoint()
        import uuid

        from photo_organizer.search.selection import now

        with connect(state) as c:
            commit_guard(c)
            c.execute(
                "UPDATE assets SET caption=?,category=?,vision_state='complete',vision_version=?,vision_error=NULL WHERE hash=?",
                (label["caption"], label["category"], provider.version, row["hash"]),
            )
            c.execute("DELETE FROM tags WHERE hash=?", (row["hash"],))
            c.executemany(
                "INSERT OR IGNORE INTO tags VALUES(?,?)",
                [(row["hash"], t.casefold().strip()) for t in label["tags"]],
            )
            c.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    row["hash"],
                    "visual",
                    provider.version,
                    json.dumps({"kind": "provider", "model": provider.model}),
                    json.dumps(label, ensure_ascii=False),
                    now(),
                ),
            )
        return {"usage": metrics["usage"]}
    if operation == "review":
        from photo_organizer.search.predicates import condition_key

        key = condition_key(spec["condition"])
        version = provider.version + "-judge-v1"
        with connect(state) as c:
            if c.execute(
                "SELECT 1 FROM judgments WHERE hash=? AND condition_id=? AND version=?",
                (row["hash"], key, version),
            ).fetchone():
                return {"cached": True}
        obj, metrics = provider.judge(asset["derivative"], spec["condition"])
        checkpoint()
        with connect(state) as c:
            commit_guard(c)
            c.execute(
                "INSERT INTO conditions VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version",
                (key, spec["condition"], version),
            )
            c.execute(
                "INSERT OR REPLACE INTO judgments VALUES(?,?,?,?,?)",
                (row["hash"], key, version, obj["verdict"], obj["evidence"]),
            )
        return {"verdict": obj["verdict"], "usage": metrics["usage"]}
    raise ValueError("unsupported job operation")
