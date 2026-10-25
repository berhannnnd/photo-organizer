"""Versioned membership proposals, safe naming, collections and plan inspection."""

import json
import string
import unicodedata
import uuid
from pathlib import Path

from photo_organizer.search.selection import members, now, save
from photo_organizer.storage.catalog import connect, writer_lock


def safe_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.encode()) > 180:
        raise ValueError("group/name must be 1..180 UTF-8 bytes")
    if (
        name in (".", "..")
        or any(ch in name for ch in '/\\<>:"|?*')
        or any(ord(ch) < 32 for ch in name)
        or name[-1] in " ."
    ):
        raise ValueError("unsafe group/name")
    if name.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("reserved filename")
    return unicodedata.normalize("NFC", name)


def propose(state, result_id, groups, parent_id=None, overlap="error", reason=""):
    if overlap not in ("error", "first", "multi"):
        raise ValueError("invalid overlap")
    if not isinstance(groups, list) or not 1 <= len(groups) <= 200:
        raise ValueError("provide 1..200 groups")
    if not isinstance(reason, str) or len(reason) > 2000:
        raise ValueError("invalid reason")
    with writer_lock(state), connect(state) as c:
        rows = members(c, result_id)
        allowed = {r["file_id"] for r in rows}
        if parent_id:
            old = c.execute("SELECT result_id FROM group_specs WHERE id=?", (parent_id,)).fetchone()
            if not old or old[0] != result_id:
                raise ValueError("group revision belongs to another input")
        normalized = []
        seen_names = set()
        assigned = set()
        conflicts = set()
        for group in groups:
            if not isinstance(group, dict) or set(group) != {"path", "ids"}:
                raise ValueError("groups require path and ids")
            if not isinstance(group["path"], list) or not 1 <= len(group["path"]) <= 8:
                raise ValueError("group path needs 1..8 names")
            path = [safe_name(n) for n in group["path"]]
            key = "/".join(path).casefold()
            if key in seen_names:
                raise ValueError("duplicate normalized group path")
            seen_names.add(key)
            ids = group["ids"]
            if (
                not isinstance(ids, list)
                or any(type(i) is not int for i in ids)
                or len(set(ids)) != len(ids)
                or not set(ids) <= allowed
            ):
                raise ValueError("invalid/out-of-scope group members")
            conflicts |= assigned & set(ids)
            if overlap == "first":
                ids = [i for i in ids if i not in assigned]
            assigned.update(ids)
            normalized.append({"path": path, "ids": ids})
        if overlap == "error" and conflicts:
            raise ValueError("overlapping groups require explicit policy")
        gid = uuid.uuid4().hex
        definition = {
            "groups": normalized,
            "overlap": overlap,
            "reason": reason,
            "unassigned": sorted(allowed - assigned),
        }
        c.execute(
            "INSERT INTO group_specs VALUES(?,?,?,?,?)",
            (gid, result_id, parent_id, json.dumps(definition, ensure_ascii=False), now()),
        )
    return {
        "group_spec_id": gid,
        "result_set_id": result_id,
        "groups": [{"path": g["path"], "count": len(g["ids"])} for g in normalized],
        "unassigned": len(allowed - assigned),
        "selected": len(rows),
    }


def group_detail(state, group_spec_id):
    with connect(state) as c:
        r = c.execute("SELECT * FROM group_specs WHERE id=?", (group_spec_id,)).fetchone()
        if not r:
            raise ValueError("unknown group spec")
        return {**dict(r), "definition": json.loads(r["definition"])}


def group_paths(c, group_spec_id, result_id):
    row = c.execute("SELECT * FROM group_specs WHERE id=?", (group_spec_id,)).fetchone()
    if not row or row["result_id"] != result_id:
        raise ValueError("group spec must use the same result snapshot")
    definition = json.loads(row["definition"])
    paths = {}
    for group in definition["groups"]:
        for fid in group["ids"]:
            paths.setdefault(fid, []).append("/".join(group["path"]))
    for fid in definition["unassigned"]:
        paths[fid] = ["unclassified"]
    return paths


def filename(template, row, group, sequence, suffix):
    fields = {
        "year": row["taken"][:4] if row["taken"] else "date-unknown",
        "month": row["taken"][5:7] if row["taken"] else "date-unknown",
        "day": row["taken"][8:10] if row["taken"] else "date-unknown",
        "category": group.split("/")[-1],
        "original": Path(row["path"]).stem,
        "sequence": str(sequence).zfill(6),
        "id": str(row["id"]),
        "hash": row["hash"][:12],
    }
    if not isinstance(template, str) or len(template) > 500:
        raise ValueError("invalid naming template")
    for _, field, fmt, conversion in string.Formatter().parse(template):
        if field is not None and (field not in fields or fmt or conversion):
            raise ValueError("unsupported naming template field or format")
    name = template.format_map(fields)
    return safe_name(name + suffix)


def plan_detail(state, plan_id, limit=50, offset=0):
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        raise ValueError("invalid pagination")
    with connect(state) as c:
        p = c.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not p:
            raise ValueError("unknown plan")
        count = c.execute("SELECT count(*) FROM actions WHERE plan_id=?", (plan_id,)).fetchone()[0]
        rows = c.execute(
            "SELECT * FROM actions WHERE plan_id=? ORDER BY file_id,relative LIMIT ? OFFSET ?",
            (plan_id, limit, offset),
        ).fetchall()
        return {
            **dict(p),
            "spec": json.loads(p["spec"]),
            "total": count,
            "items": [dict(r) for r in rows],
            "states": dict(
                c.execute(
                    "SELECT CASE WHEN error IS NOT NULL THEN 'failed' ELSE status END,count(*) FROM actions WHERE plan_id=? GROUP BY 1",
                    (plan_id,),
                )
            ),
            "next_offset": offset + limit if offset + limit < count else None,
        }


def record_collection(c, plan):
    # One persistent collection per plan, with paths preserving nested groups.
    cid = plan["id"]
    actions = c.execute(
        "SELECT * FROM actions WHERE plan_id=? AND status='done' AND error IS NULL ORDER BY file_id,relative",
        (cid,),
    ).fetchall()
    rows = {
        a["file_id"]: {
            "file_id": a["file_id"],
            "hash": a["hash"],
            "path": a["source"],
            "verdict": "matched",
        }
        for a in actions
    }
    rid = save(
        c,
        list(rows.values()),
        {"collection_plan": cid},
        ctx={"coverage": "executed_members", "requirements": []},
    )
    c.execute(
        "INSERT INTO collections VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET result_id=excluded.result_id",
        (cid, "Organization " + cid[:8], rid, cid, now()),
    )
    c.execute("DELETE FROM collection_members WHERE collection_id=?", (cid,))
    c.executemany(
        "INSERT INTO collection_members VALUES(?,?,?,?,?)",
        [
            (cid, a["file_id"], a["hash"], a["source"], str(Path(a["relative"]).parent))
            for a in actions
        ],
    )
    return cid, rid


def collection(state, collection_id=None, name=None, group=None):
    with writer_lock(state), connect(state) as c:
        if collection_id is None:
            return {
                "collections": [
                    dict(r)
                    for r in c.execute("SELECT * FROM collections ORDER BY created DESC LIMIT 100")
                ]
            }
        r = c.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        if not r:
            raise ValueError("unknown collection")
        if name is not None:
            c.execute("UPDATE collections SET name=? WHERE id=?", (safe_name(name), collection_id))
        rid = r["result_id"]
        if group is not None:
            selected = c.execute(
                "SELECT * FROM collection_members WHERE collection_id=? AND group_path=?",
                (collection_id, group),
            ).fetchall()
            rid = save(
                c,
                [
                    {
                        "file_id": x["file_id"],
                        "hash": x["hash"],
                        "path": x["path"],
                        "verdict": "matched",
                    }
                    for x in selected
                ],
                {"collection": collection_id, "group": group},
                r["result_id"],
            )
        return {
            "collection_id": collection_id,
            "name": name or r["name"],
            "result_set_id": rid,
            "groups": dict(
                c.execute(
                    "SELECT group_path,count(*) FROM collection_members WHERE collection_id=? GROUP BY group_path",
                    (collection_id,),
                )
            ),
        }
