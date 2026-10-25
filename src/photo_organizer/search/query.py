"""Conservative SQL search. Result snapshots are managed by results.py."""

import time

from photo_organizer.search.predicates import condition_key, predicate
from photo_organizer.storage.catalog import report


def compile_rule(rule):
    sql, args = predicate(rule)
    return "f.present=1 AND f.error IS NULL AND (" + sql + ")", args


def select(c, rule):
    where, args = compile_rule(rule)
    return c.execute(
        "SELECT f.id,f.path,f.hash,a.taken,a.width,a.height,a.category,a.vision_state FROM files f JOIN assets a ON a.hash=f.hash WHERE "
        + where
        + " ORDER BY f.id",
        args,
    ).fetchall()


def search(c, rule, limit=50, offset=0):
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("invalid pagination")
    start = time.perf_counter()
    sql, args = predicate(rule)
    counts = dict(
        c.execute(
            "SELECT CASE WHEN f.error IS NOT NULL THEN 'error' WHEN ("
            + sql
            + ") THEN 'matched' WHEN NOT ("
            + sql
            + ") THEN 'not_matched' ELSE 'unknown_or_unanalyzed' END,count(*) FROM files f LEFT JOIN assets a ON a.hash=f.hash WHERE f.present=1 GROUP BY 1",
            args + args,
        ).fetchall()
    )
    where, args = compile_rule(rule)
    rows = c.execute(
        "SELECT f.id,f.path,f.hash,a.taken,a.caption,a.category FROM files f JOIN assets a ON a.hash=f.hash WHERE "
        + where
        + " ORDER BY f.id LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return {
        "total": counts.get("matched", 0),
        "items": [dict(r) for r in rows],
        "offset": offset,
        "limit": limit,
        "coverage": report(c),
        "judgments": counts,
        "seconds": time.perf_counter() - start,
        "model_calls": 0,
        "scope_note": "Indexed evidence only; unknown and unanalyzed are not negative matches.",
    }


def semantic_coverage(c, text, result_set_id=None):
    key = condition_key(text)
    scope = (
        " AND f.id IN(SELECT file_id FROM result_members WHERE result_id=? AND verdict IN ('matched','candidate'))"
        if result_set_id
        else ""
    )
    return dict(
        c.execute(
            "SELECT COALESCE(j.verdict,'not_indexed'),count(*) FROM files f LEFT JOIN judgments j ON j.hash=f.hash AND j.condition_id=? AND j.version=(SELECT version FROM conditions WHERE id=?) WHERE f.present=1"
            + scope
            + " GROUP BY COALESCE(j.verdict,'not_indexed')",
            (key, key, result_set_id) if result_set_id else (key, key),
        ).fetchall()
    )
