"""Explain three-valued rule results while preserving unanalyzed evidence."""

import json

from photo_organizer.search.predicates import condition_key, predicate


def evaluate(c, row, rule, scope_ids=()):
    parts = []
    for op in ("and", "or"):
        if op in rule:
            children = [evaluate(c, row, x, scope_ids) for x in rule[op]]
            parts.append(combine(children, op))
    if "not" in rule:
        child = evaluate(c, row, rule["not"], scope_ids)
        parts.append(
            {
                **child,
                "verdict": {"matched": "not_matched", "not_matched": "matched"}.get(
                    child["verdict"], child["verdict"]
                ),
            }
        )
    for field, value in rule.items():
        if field in ("and", "or", "not"):
            continue
        if field == "semantic":
            key = condition_key(value)
            correction = None
            for scope in (*scope_ids, ""):
                correction = c.execute(
                    "SELECT value,source FROM corrections WHERE hash=? AND field=? AND scope_id=? ORDER BY created DESC,id DESC LIMIT 1",
                    (row["hash"], "semantic:" + key, scope),
                ).fetchone()
                if correction:
                    break
            if correction:
                verdict = json.loads(correction["value"])
                reason = "user_correction"
                parts.append(
                    {
                        "verdict": {"yes": "matched", "no": "not_matched", "uncertain": "unknown"}[
                            verdict
                        ],
                        "field": field,
                        "condition": value,
                        "reason": reason,
                    }
                )
                continue
            j = c.execute(
                "SELECT j.* FROM judgments j JOIN conditions d ON j.condition_id=d.id AND j.version=d.version WHERE j.hash=? AND d.id=?",
                (row["hash"], key),
            ).fetchone()
            parts.append(
                {
                    "verdict": {"yes": "matched", "no": "not_matched", "uncertain": "unknown"}[
                        j["verdict"]
                    ]
                    if j
                    else "unanalyzed",
                    "field": field,
                    "condition": value,
                    "evidence": j["evidence"] if j else None,
                    "version": j["version"] if j else None,
                }
            )
            continue
        sql, args = predicate({field: value})
        val = c.execute(
            "SELECT (" + sql + ") FROM files f LEFT JOIN assets a ON a.hash=f.hash WHERE f.id=?",
            (*args, row["id"]),
        ).fetchone()[0]
        status = "matched" if val == 1 else "not_matched" if val == 0 else "unknown"
        if val is None and field in (
            "all_tags",
            "any_tags",
            "not_tags",
            "caption_text",
            "category",
        ):
            status = "unanalyzed" if row["vision_state"] != "complete" else "unknown"
        parts.append(
            {
                "verdict": status,
                "field": field,
                "reason": "missing_or_insufficient_evidence" if val is None else "indexed_evidence",
            }
        )
    return combine(parts, "and")


def combine(parts, op):
    states = [p["verdict"] for p in parts]
    if op == "and":
        state = (
            "not_matched"
            if "not_matched" in states
            else "unanalyzed"
            if "unanalyzed" in states
            else "unknown"
            if "unknown" in states
            else "matched"
        )
    else:
        state = (
            "matched"
            if "matched" in states
            else "unanalyzed"
            if "unanalyzed" in states
            else "unknown"
            if "unknown" in states
            else "not_matched"
        )
    return {"verdict": state, "operator": op, "evidence": parts}


def semantic_requirements(rule):
    found = set()
    if "semantic" in rule:
        found.add(rule["semantic"].strip())
    for child in rule.get("and", []):
        found |= semantic_requirements(child)
    return found
