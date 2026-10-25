"""Full-scope semantic metrics from independent, content-addressed labels."""

import hashlib
import json
from collections import defaultdict


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def metrics(tp, fp, fn):
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def score(truth, predictions):
    """Require complete labels, retain disputed evidence, and count unreturned positives as FN."""
    scope = set(truth["scope_hashes"])
    if not scope or len(scope) != len(truth["scope_hashes"]):
        raise ValueError("scope must contain distinct content hashes")
    queries = truth["queries"]
    if not isinstance(queries, list) or len({q["id"] for q in queries}) != len(queries):
        raise ValueError("distinct query IDs required")
    if set(predictions) - {q["id"] for q in queries}:
        raise ValueError("prediction contains unknown query")
    reports = []
    groups = defaultdict(list)
    for query in queries:
        labels = query["labels"]
        if set(labels) != scope or any(v not in ("yes", "no", "disputed") for v in labels.values()):
            raise ValueError("every scoped content needs yes/no/disputed truth for every query")
        raw = predictions.get(query["id"], [])
        if (
            not isinstance(raw, list)
            or any(not isinstance(v, str) for v in raw)
            or not set(raw) <= scope
        ):
            raise ValueError("ranked predictions must be scoped hashes")
        ranked = list(dict.fromkeys(raw))
        predicted = set(ranked)
        positives = {h for h, value in labels.items() if value == "yes"}
        negatives = {h for h, value in labels.items() if value == "no"}
        disputed = scope - positives - negatives
        result = {
            "id": query["id"],
            "group": query["group"],
            **metrics(
                len(predicted & positives), len(predicted & negatives), len(positives - predicted)
            ),
            "positives": len(positives),
            "disputed": len(disputed),
            "disputed_fraction": len(disputed) / len(scope),
            "disputed_returned": len(predicted & disputed),
            "duplicate_predictions": len(raw) - len(ranked),
            "recall_at_10": len(set(ranked[:10]) & positives) / len(positives)
            if positives
            else None,
            "recall_at_50": len(set(ranked[:50]) & positives) / len(positives)
            if positives
            else None,
            "prediction_missing": query["id"] not in predictions,
        }
        reports.append(result)
        groups[query["group"]].append(result)

    def aggregate(rows):
        return {
            "queries": len(rows),
            "micro": metrics(*(sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))),
            "macro": {
                k: sum(r[k] for r in rows if r[k] is not None) / sum(r[k] is not None for r in rows)
                if any(r[k] is not None for r in rows)
                else None
                for k in ("precision", "recall")
            },
        }

    accepted_truth = (
        truth.get("annotation_source") == "independent_human"
        and truth.get("disputes_reviewed") is True
    )
    group_reports = {name: aggregate(rows) for name, rows in groups.items()}
    expected = {"subject", "scene_attribute", "boolean_count", "paraphrase", "example", "relation"}
    protocol_ready = (
        set(groups) == expected
        and all(len(rows) >= 10 for rows in groups.values())
        and len(scope) >= 300
    )
    insufficient = [
        r["id"] for r in reports if r["positives"] < (20 if r["group"] == "subject" else 1)
    ]
    failed = [
        r["id"]
        for r in reports
        if (
            r["precision"] is None
            or r["precision"] < (0.95 if r["group"] == "subject" else 0.9)
            or r["recall"] is None
            or r["recall"] < (0.9 if r["group"] == "subject" else 0.85)
        )
    ]
    return {
        "truth_digest": digest(truth),
        "predictions_digest": digest(predictions),
        "scope_contents": len(scope),
        "queries": reports,
        "groups": group_reports,
        "overall": aggregate(reports),
        "gate": "unmeasured"
        if not accepted_truth or not protocol_ready or insufficient
        else "failed"
        if failed
        else "passed",
        "independent_truth": accepted_truth,
        "protocol_ready": protocol_ready,
        "insufficient_positive_queries": insufficient,
        "failed_queries": failed,
        "note": "Ranking is not probability. Unreturned positives, including unknown/unanalyzed predictions, count as false negatives.",
    }
