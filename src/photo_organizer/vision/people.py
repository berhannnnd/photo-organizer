"""Face features, deterministic same-person proposals and explicit user corrections."""

import base64
import hashlib
import json
import math
import uuid
from pathlib import Path

from photo_organizer.capabilities.adapters.http import request
from photo_organizer.capabilities.registry import get_config
from photo_organizer.core.errors import CapabilityError
from photo_organizer.core.paging import page, validate
from photo_organizer.runtime.context import admit, checkpoint
from photo_organizer.search.selection import members, now
from photo_organizer.storage.catalog import connect, writer_lock


def detect(config, path):
    if config["protocol"] == "photo-http":
        output = request(
            config,
            {
                "operation": "faces",
                "model": config["model"],
                "image": base64.b64encode(Path(path).read_bytes()).decode(),
            },
        )
        if output.get("space") != config.get("space"):
            raise CapabilityError("incompatible_space", "Face feature space mismatch")
        rows = output.get("faces")
    elif config["protocol"] == "opencv":
        try:
            import cv2
        except ImportError:
            raise CapabilityError(
                "dependency_missing",
                "Install optional opencv-python and provide YuNet/SFace model files",
            ) from None
        admit(remote=False)
        im = cv2.imread(str(path))
        if im is None:
            raise CapabilityError("invalid_image", "OpenCV could not decode input")
        detector = cv2.FaceDetectorYN.create(
            config["detector_path"], "", (im.shape[1], im.shape[0])
        )
        recognizer = cv2.FaceRecognizerSF.create(config["recognizer_path"], "")
        _, faces = detector.detect(im)
        rows = []
        for f in faces if faces is not None else []:
            feature = recognizer.feature(recognizer.alignCrop(im, f)).flatten().tolist()
            rows.append({"box": [float(v) for v in f[:4]], "vector": feature})
    else:
        raise CapabilityError("host_action_required", "Use host face extraction and face-submit")
    if not isinstance(rows, list) or len(rows) > 200:
        raise CapabilityError("invalid_response", "Invalid face response")
    return rows


def submit(state, result_id, records, space, source, version):
    from photo_organizer.search.embeddings import pack
    from photo_organizer.vision.evidence import source_record

    source = source_record(source)
    if not all(isinstance(x, str) and 1 <= len(x) <= 300 for x in (space, version)):
        raise ValueError("face space and version required")
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError("provide 1..100 face records")
    with writer_lock(state), connect(state) as c:
        scope = {r["file_id"]: r for r in members(c, result_id)}
        validated = []
        for r in records:
            if r.get("file_id") not in scope or r.get("hash") != scope[r["file_id"]]["hash"]:
                raise ValueError("out-of-scope/stale face record")
            box = r.get("box")
            if (
                not isinstance(box, list)
                or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                or min(box) < 0
                or box[2] <= 0
                or box[3] <= 0
            ):
                raise ValueError("invalid face box xywh")
            vector = pack(r.get("vector"))
            fid = hashlib.sha256(json.dumps([r["hash"], space, box, version]).encode()).hexdigest()
            validated.append(
                (fid, r["hash"], space, json.dumps(box), vector, json.dumps(source), version)
            )
        dims = {len(r[4]) for r in validated}
        existing = c.execute(
            "SELECT length(vector) FROM faces WHERE space=? LIMIT 1", (space,)
        ).fetchone()
        if len(dims) > 1 or existing and dims != {existing[0]}:
            raise ValueError("face vector dimensions differ")
        for values in validated:
            c.execute(
                "INSERT INTO faces(id,hash,space,box,vector,source,version) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                values,
            )
    return {"saved": len(validated), "space": space}


def index_one(state, result_id, row):
    config = get_config(state, "faces")
    with connect(state) as c:
        path = c.execute("SELECT derivative FROM assets WHERE hash=?", (row["hash"],)).fetchone()[0]
    revision = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if config["protocol"] == "opencv":
        revision = hashlib.sha256(
            (
                revision
                + hashlib.sha256(Path(config["detector_path"]).read_bytes()).hexdigest()
                + hashlib.sha256(Path(config["recognizer_path"]).read_bytes()).hexdigest()
            ).encode()
        ).hexdigest()
    space = config.get("space", revision)
    with connect(state) as c:
        cached = c.execute(
            "SELECT payload FROM observations WHERE hash=? AND kind='face_detection' AND version=? ORDER BY created DESC LIMIT 1",
            (row["hash"], revision),
        ).fetchone()
        if cached:
            return {**json.loads(cached[0]), "cached": True}
    output = detect(config, path)
    checkpoint()
    if output:
        submit(
            state,
            result_id,
            [{**r, "file_id": row["file_id"], "hash": row["hash"]} for r in output],
            space,
            {"kind": "provider", "model": config.get("model", "opencv"), "version": revision},
            revision,
        )
    with connect(state) as c:
        c.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                row["hash"],
                "face_detection",
                revision,
                json.dumps({"kind": "provider"}),
                json.dumps({"count": len(output), "space": space}),
                now(),
            ),
        )
    return {"faces": len(output), "space": space}


def cluster(state, space, threshold=0.6):
    from photo_organizer.search.embeddings import unpack

    if type(threshold) not in (int, float) or not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1; calibrate on your face model")
    with writer_lock(state), connect(state) as c:
        rows = c.execute("SELECT f.* FROM faces f WHERE space=? ORDER BY id", (space,)).fetchall()
        groups = []
        for row in rows:
            fixed = c.execute(
                "SELECT person_id FROM face_constraints WHERE face_id=?", (row["id"],)
            ).fetchone()
            if fixed:
                c.execute("UPDATE faces SET person_id=? WHERE id=?", (fixed[0], row["id"]))
                continue
            vector = unpack(row["vector"])
            target = None
            # Complete-link membership avoids unbounded similarity chaining.
            for pid, features in groups:
                if all(sum(a * b for a, b in zip(vector, v)) >= threshold for v in features):
                    target = (pid, features)
                    break
            if target is None:
                pid = hashlib.sha256((space + row["id"]).encode()).hexdigest()[:32]
                c.execute("INSERT OR IGNORE INTO people(id,created) VALUES(?,?)", (pid, now()))
                target = (pid, [])
                groups.append(target)
            target[1].append(vector)
            c.execute("UPDATE faces SET person_id=? WHERE id=?", (target[0], row["id"]))
    return {
        "space": space,
        "faces": len(rows),
        "proposed_groups": len(groups),
        "threshold": threshold,
        "identity_names_inferred": False,
    }


def manage(
    state,
    action="list",
    person_id=None,
    name=None,
    face_ids=None,
    merge_ids=None,
    limit=50,
    offset=0,
):
    validate(limit, offset)
    with writer_lock(state), connect(state) as c:
        if action == "list":
            total = c.execute(
                "SELECT count(*) FROM people p WHERE EXISTS(SELECT 1 FROM faces f WHERE f.person_id=p.id)"
            ).fetchone()[0]
            items = [
                dict(r)
                for r in c.execute(
                    "SELECT p.*,count(f.id) AS faces FROM people p JOIN faces f ON p.id=f.person_id GROUP BY p.id ORDER BY p.id LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]
            return page(items, total, limit, offset, "people")
        if action == "faces":
            total = c.execute(
                "SELECT count(*) FROM faces WHERE person_id=?", (person_id,)
            ).fetchone()[0]
            items = [
                dict(r)
                for r in c.execute(
                    "SELECT id,hash,space,box,person_id FROM faces WHERE person_id=? ORDER BY id LIMIT ? OFFSET ?",
                    (person_id, limit, offset),
                )
            ]
            return page(items, total, limit, offset, "faces")
        if action not in ("rename", "merge", "assign", "split"):
            raise ValueError("invalid person action")
        if (
            action in ("rename", "merge", "assign")
            and not c.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone()
        ):
            raise ValueError("unknown person")
        if action == "rename":
            from photo_organizer.organizing.organization import safe_name

            c.execute(
                "UPDATE people SET name=?,version=version+1 WHERE id=?",
                (safe_name(name), person_id),
            )
        else:
            if action == "merge":
                if not isinstance(merge_ids, list) or not merge_ids:
                    raise ValueError("merge_ids required")
                face_ids = []
                for pid in merge_ids:
                    if not c.execute("SELECT 1 FROM people WHERE id=?", (pid,)).fetchone():
                        raise ValueError("unknown merge person")
                    face_ids.extend(
                        r[0] for r in c.execute("SELECT id FROM faces WHERE person_id=?", (pid,))
                    )
            if (
                not isinstance(face_ids, list)
                or not face_ids
                or len(set(face_ids)) != len(face_ids)
            ):
                raise ValueError("distinct face_ids required")
            for fid in face_ids:
                if not c.execute("SELECT 1 FROM faces WHERE id=?", (fid,)).fetchone():
                    raise ValueError("unknown face")
            if action == "split":
                person_id = uuid.uuid4().hex
                c.execute(
                    "INSERT INTO people(id,name,created) VALUES(?,?,?)", (person_id, name, now())
                )
            for fid in face_ids:
                c.execute("UPDATE faces SET person_id=? WHERE id=?", (person_id, fid))
                c.execute(
                    "INSERT INTO face_constraints VALUES(?,?,?) ON CONFLICT(face_id) DO UPDATE SET person_id=excluded.person_id,updated=excluded.updated",
                    (fid, person_id, now()),
                )
        return {"person_id": person_id, "action": action}
