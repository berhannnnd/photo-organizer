"""Immutable selection, set algebra and explicit ranking inside frozen scopes."""

import datetime
import json
import uuid

from photo_organizer.search import results
from photo_organizer.storage.catalog import connect, writer_lock


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def context(c, rid):
    saved = c.execute("SELECT context FROM result_context WHERE result_id=?", (rid,)).fetchone()
    if saved:
        return json.loads(saved[0])
    row = results.require(c, rid)
    rule = json.loads(row["rule"])
    if "retrieval" in rule:
        inherited = context(c, row["parent_id"]) if row["parent_id"] else {}
        return {
            **inherited,
            "coverage": "ranked_subset",
            "requirements": sorted(set(inherited.get("requirements", [])) | {rule["retrieval"]}),
            "origin": rid,
        }
    if row["parent_id"]:
        return context(c, row["parent_id"])
    return {"coverage": "evaluated_scope", "requirements": [], "origin": rid}


def retrieval_context(c, parent_id, criterion, **coverage):
    """Retain every unresolved ancestor criterion when narrowing a candidate scope."""
    inherited = context(c, parent_id)
    return {
        **inherited,
        **coverage,
        "explicit_selection": False,
        "requirements": sorted(set(inherited.get("requirements", [])) | {criterion}),
    }


def members(c, rid, verdicts=("matched", "candidate")):
    results.require(c, rid)
    if results.stale_count(c, rid):
        raise ValueError("snapshot has stale members; refresh explicitly")
    rows = [
        dict(r)
        for r in c.execute(
            "SELECT * FROM result_members WHERE result_id=? ORDER BY score DESC,file_id", (rid,)
        )
        if r["verdict"] in verdicts
    ]
    for row in rows:
        current = c.execute(
            "SELECT hash,present,error FROM files WHERE id=?", (row["file_id"],)
        ).fetchone()
        if (
            not current
            or not current["present"]
            or current["error"]
            or current["hash"] != row["hash"]
        ):
            raise ValueError("snapshot has stale members; refresh explicitly")
    return rows


def save(c, rows, rule, parent_id=None, ctx=None, details=None):
    results.initialize(c)
    rid = uuid.uuid4().hex
    counts = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    c.execute(
        "INSERT INTO result_sets VALUES(?,?,?,?,?)",
        (rid, now(), parent_id, json.dumps(rule, ensure_ascii=False), json.dumps(counts)),
    )
    c.executemany(
        "INSERT INTO result_members(result_id,file_id,hash,path,verdict,score) VALUES(?,?,?,?,?,?)",
        [(rid, r["file_id"], r["hash"], r["path"], r["verdict"], r.get("score")) for r in rows],
    )
    c.execute(
        "INSERT INTO result_context VALUES(?,?)",
        (
            rid,
            json.dumps(
                ctx or {"coverage": "explicit_selection", "requirements": []}, ensure_ascii=False
            ),
        ),
    )
    details = dict(details or {})
    for row in rows:
        snapshot = c.execute(
            "SELECT caption,category,taken,vision_version FROM effective_assets WHERE hash=?",
            (row["hash"],),
        ).fetchone()
        if snapshot:
            details[row["file_id"]] = {
                **details.get(row["file_id"], {}),
                "snapshot": dict(snapshot),
            }
    if details:
        c.executemany(
            "INSERT INTO result_details VALUES(?,?,?)",
            [(rid, fid, json.dumps(detail, ensure_ascii=False)) for fid, detail in details.items()],
        )
    return rid


def choose(state, result_id, ids, mode="keep", source="agent", reason="", verdicts=None):
    if mode not in ("keep", "exclude", "order"):
        raise ValueError("mode must be keep, exclude or order")
    if source not in ("agent", "user"):
        raise ValueError("source must be agent or user")
    if (
        not isinstance(ids, list)
        or len(ids) != len(set(ids))
        or any(type(i) is not int for i in ids)
    ):
        raise ValueError("ids must be distinct integers")
    if not isinstance(reason, str) or len(reason) > 2000:
        raise ValueError("invalid reason")
    allowed = (
        "matched",
        "candidate",
        "not_matched",
        "unknown",
        "unanalyzed",
        "unknown_or_unanalyzed",
        "error",
    )
    if verdicts is not None and (
        not isinstance(verdicts, list) or not verdicts or any(v not in allowed for v in verdicts)
    ):
        raise ValueError("invalid verdicts")
    with writer_lock(state), connect(state) as c:
        results.initialize(c)
        rows = members(c, result_id, tuple(verdicts) if verdicts else ("matched", "candidate"))
        by_id = {r["file_id"]: r for r in rows}
        if not set(ids) <= by_id.keys():
            raise ValueError("selection contains members outside input scope")
        if mode == "keep":
            rows = [by_id[i] for i in ids]
        elif mode == "exclude":
            rows = [r for r in rows if r["file_id"] not in ids]
        else:
            if set(ids) != by_id.keys():
                raise ValueError("order must contain every selected member exactly once")
            rows = [by_id[i] for i in ids]
        if any(r["hash"] is None or r["verdict"] == "error" for r in rows):
            raise ValueError("cannot select unavailable members")
        for n, r in enumerate(rows):
            r["score"] = len(rows) - n
            # Explicit selection is sufficient to organize; it is not a semantic proof.
            if mode != "order":
                r["verdict"] = "matched"
        ctx = context(c, result_id)
        ctx = {
            **ctx,
            "selection_source": source,
            "selection_reason": reason,
            "explicit_selection": mode != "order",
        }
        if mode != "order":
            ctx["unverified_requirements"] = ctx.get("requirements", [])
            ctx["requirements"] = []
        rid = save(
            c,
            rows,
            {"selection": mode, "ids": ids, "source": source, "reason": reason},
            result_id,
            ctx,
        )
    return results.page(state, rid)


def combine(state, result_ids, operation="union", identity="file", reason=""):
    if not isinstance(reason, str) or len(reason) > 2000:
        raise ValueError("invalid combination reason")
    if not isinstance(result_ids, list) or not 2 <= len(result_ids) <= 20:
        raise ValueError("provide 2..20 result IDs")
    if operation not in ("union", "intersection", "difference") or identity not in (
        "file",
        "content",
    ):
        raise ValueError("invalid set operation or identity")
    with writer_lock(state), connect(state) as c:
        results.initialize(c)
        groups = [members(c, rid) for rid in result_ids]

        def key(r):
            return r["file_id"] if identity == "file" else r["hash"]

        sets = [{key(r) for r in group} for group in groups]
        keys = sets[0].copy()
        for other in sets[1:]:
            if operation == "union":
                keys |= other
            elif operation == "intersection":
                keys &= other
            else:
                keys -= other
        chosen = {}
        copies = {}
        for group in groups:
            for r in group:
                k = key(r)
                if k not in keys:
                    continue
                copies.setdefault(str(k), set()).add(r["file_id"])
                if k in chosen and (chosen[k]["hash"] != r["hash"]):
                    raise ValueError("inconsistent source versions")
                if k not in chosen:
                    chosen[k] = r
                elif r["verdict"] == "candidate":
                    chosen[k]["verdict"] = "candidate"
        contexts = [context(c, rid) for rid in result_ids]
        ctx = {
            "coverage": "composed_scopes",
            "combination_reason": reason,
            "inputs": result_ids,
            "input_contexts": contexts,
            "requirements": sorted({r for ctx in contexts for r in ctx.get("requirements", [])}),
            "duplicate_instances": {k: sorted(v) for k, v in copies.items() if len(v) > 1},
        }
        rid = save(
            c,
            list(chosen.values()),
            {"set_operation": operation, "identity": identity, "inputs": result_ids},
            result_ids[0],
            ctx,
        )
    return results.page(state, rid)
