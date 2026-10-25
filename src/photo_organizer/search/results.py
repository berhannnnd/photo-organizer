"""Persistent membership snapshots, bounded paging, and parent-scoped refinement."""

import json

from photo_organizer.search.predicates import predicate
from photo_organizer.storage.catalog import connect, writer_lock

SCHEMA = """
CREATE TABLE IF NOT EXISTS result_sets(
 id TEXT PRIMARY KEY, created TEXT NOT NULL, parent_id TEXT, rule TEXT NOT NULL,
 counts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS result_members(
 result_id TEXT NOT NULL, file_id INTEGER NOT NULL, hash TEXT, path TEXT NOT NULL,
 verdict TEXT NOT NULL, PRIMARY KEY(result_id,file_id));
CREATE INDEX IF NOT EXISTS result_page ON result_members(result_id,verdict,file_id);
"""


def initialize(c):
    c.executescript(SCHEMA)
    if "score" not in {r[1] for r in c.execute("PRAGMA table_info(result_members)")}:
        with c:
            c.execute("BEGIN IMMEDIATE")
            if "score" not in {r[1] for r in c.execute("PRAGMA table_info(result_members)")}:
                c.execute("ALTER TABLE result_members ADD COLUMN score REAL")


def require(c, result_id):
    row = c.execute("SELECT * FROM result_sets WHERE id=?", (result_id,)).fetchone()
    if row is None:
        raise ValueError("unknown result_set_id")
    return row


def stale_count(c, result_id):
    return c.execute(
        """SELECT count(*) FROM result_members m LEFT JOIN files f ON f.id=m.file_id
        WHERE m.result_id=? AND m.verdict IN ('matched','candidate')
        AND (f.id IS NULL OR f.present!=1 OR f.error IS NOT NULL OR f.hash IS NOT m.hash)""",
        (result_id,),
    ).fetchone()[0]


def create(state, rule, parent_id=None):
    # Bound the total AST before recursive compilation and SQLite parameter expansion.
    encoded = json.dumps(rule, ensure_ascii=False)
    if len(encoded) > 16000:
        raise ValueError("rule exceeds 16000 characters")
    sql, params = predicate(rule)
    with writer_lock(state), connect(state) as c:
        initialize(c)
        with c:
            c.execute("BEGIN IMMEDIATE")
            if parent_id:
                require(c, parent_id)
                if stale_count(c, parent_id):
                    raise ValueError("parent snapshot has stale members; refresh explicitly")
            scope = ""
            scope_params = []
            if parent_id:
                scope = " AND f.id IN (SELECT file_id FROM result_members WHERE result_id=? AND verdict IN ('matched','candidate'))"
                scope_params.append(parent_id)
            rows = c.execute(
                "SELECT f.id,f.path,f.hash,CASE WHEN f.error IS NOT NULL THEN 'error' WHEN ("
                + sql
                + ") THEN 'matched' WHEN NOT ("
                + sql
                + ") THEN 'not_matched' ELSE 'unknown_or_unanalyzed' END AS verdict FROM files f LEFT JOIN effective_assets a ON a.hash=f.hash WHERE f.present=1 AND NOT EXISTS(SELECT 1 FROM roots rt WHERE rt.path=f.root AND (rt.status='offline' OR rt.enabled=0))"
                + scope
                + " ORDER BY f.id",
                params + params + scope_params,
            ).fetchall()
            from photo_organizer.search.evaluation import evaluate, semantic_requirements
            from photo_organizer.search.selection import context, save

            ctx = (
                context(c, parent_id)
                if parent_id
                else {"coverage": "evaluated_scope", "requirements": []}
            )
            pending = set(ctx.get("requirements", [])) - semantic_requirements(rule)
            ctx = {**ctx, "requirements": sorted(pending)}
            ancestry = []
            ancestor = parent_id
            while ancestor:
                ancestry.append(ancestor)
                ancestor = require(c, ancestor)["parent_id"]
            details = {}
            converted = []
            scores = (
                {
                    r["file_id"]: r["score"]
                    for r in c.execute(
                        "SELECT file_id,score FROM result_members WHERE result_id=?", (parent_id,)
                    )
                }
                if parent_id
                else {}
            )
            for r in rows:
                asset = c.execute(
                    "SELECT f.id,f.hash,a.vision_state FROM files f LEFT JOIN effective_assets a ON a.hash=f.hash WHERE f.id=?",
                    (r["id"],),
                ).fetchone()
                detail = (
                    {"verdict": "error"}
                    if r["verdict"] == "error"
                    else evaluate(c, asset, rule, ancestry)
                )
                verdict = detail["verdict"]
                if verdict == "matched" and pending:
                    verdict = "candidate"
                details[r["id"]] = detail
                converted.append(
                    {
                        "file_id": r["id"],
                        "hash": r["hash"],
                        "path": r["path"],
                        "verdict": verdict,
                        "score": scores.get(r["id"]),
                    }
                )
            result_id = save(c, converted, rule, parent_id, ctx, details)
    return page(state, result_id)


def page(state, result_id, limit=50, offset=0, verdict=None):
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("invalid pagination")
    if verdict not in (
        None,
        "candidate",
        "matched",
        "not_matched",
        "unknown_or_unanalyzed",
        "unknown",
        "unanalyzed",
        "error",
    ):
        raise ValueError("invalid verdict")
    with connect(state) as c:
        initialize(c)
        c.execute("BEGIN")
        result = require(c, result_id)
        counts = json.loads(result["counts"])
        if verdict is None:
            verdict = "candidate" if "candidate" in counts else "matched"
        rows = c.execute(
            """SELECT m.file_id AS id,m.hash,m.path,m.verdict,m.score,f.path AS current_path,a.caption,a.category,a.taken,a.vision_version AS observation_version,
            CASE WHEN f.id IS NULL OR f.present!=1 OR f.error IS NOT NULL OR f.hash IS NOT m.hash THEN 1 ELSE 0 END AS stale
            FROM result_members m LEFT JOIN files f ON f.id=m.file_id LEFT JOIN effective_assets a ON a.hash=m.hash
            WHERE m.result_id=? AND m.verdict=? ORDER BY m.score DESC,m.file_id LIMIT ? OFFSET ?""",
            (result_id, verdict, limit, offset),
        ).fetchall()
        from photo_organizer.search.selection import context

        ctx = context(c, result_id)
        enriched = []
        for row in rows:
            item = dict(row)
            detail = c.execute(
                "SELECT detail FROM result_details WHERE result_id=? AND file_id=?",
                (result_id, row["id"]),
            ).fetchone()
            item["judgment_detail"] = json.loads(detail[0]) if detail else None
            snapshot = item["judgment_detail"].get("snapshot") if item["judgment_detail"] else None
            item["snapshot_evidence"] = snapshot
            item["evidence_changed"] = bool(
                snapshot
                and any(
                    snapshot.get(k)
                    != item.get("observation_version" if k == "vision_version" else k)
                    for k in ("caption", "category", "taken", "vision_version")
                )
            )
            enriched.append(item)
        total = counts.get(verdict, 0)
        return {
            "result_set_id": result_id,
            "parent_id": result["parent_id"],
            "created": result["created"],
            "selection_kind": "candidates"
            if "candidate" in counts
            else "explicit_selection"
            if ctx.get("explicit_selection")
            else "evidence_matches",
            "rule": json.loads(result["rule"]),
            "judgments": counts,
            "total": total,
            "context": ctx,
            "items": enriched,
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit if offset + limit < total else None,
            "stale_members": stale_count(c, result_id),
            "unavailable_members": c.execute(
                "SELECT count(*) FROM result_members m JOIN files f ON f.id=m.file_id JOIN roots rt ON rt.path=f.root WHERE m.result_id=? AND (rt.status='offline' OR rt.enabled=0)",
                (result_id,),
            ).fetchone()[0],
            "model_calls": 0,
            "source_revisions": [
                dict(r)
                for r in c.execute(
                    "SELECT DISTINCT rt.id,rt.path,rt.status,rt.revision,rt.last_success FROM result_members m JOIN files f ON f.id=m.file_id JOIN roots rt ON rt.path=f.root WHERE m.result_id=? ORDER BY rt.id LIMIT 1000",
                    (result_id,),
                )
            ],
            "freshness": "relative_to_last_scan; run scan before operations requiring current files",
        }


def select_snapshot(c, result_id, accept_candidates=False):
    initialize(c)
    row = require(c, result_id)
    if "candidate" in json.loads(row["counts"]) and not accept_candidates:
        raise ValueError("candidate set needs review or explicit accept_candidates=true")
    if stale_count(c, result_id):
        raise ValueError("snapshot has stale members; refresh explicitly")
    unavailable = c.execute(
        "SELECT count(*) FROM result_members m JOIN files f ON f.id=m.file_id JOIN roots rt ON rt.path=f.root WHERE m.result_id=? AND m.verdict IN ('matched','candidate') AND (rt.status='offline' OR rt.enabled=0)",
        (result_id,),
    ).fetchone()[0]
    if unavailable:
        raise ValueError(
            "snapshot contains offline or disabled sources; synchronize or enable them before planning"
        )
    return c.execute(
        """SELECT f.id,f.path,f.hash,a.taken,a.width,a.height,a.category,a.vision_state
        FROM result_members m JOIN files f ON f.id=m.file_id JOIN effective_assets a ON a.hash=m.hash
        WHERE m.result_id=? AND m.verdict IN ('matched','candidate') ORDER BY f.id""",
        (result_id,),
    ).fetchall()
