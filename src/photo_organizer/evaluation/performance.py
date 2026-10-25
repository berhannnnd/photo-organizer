"""Kernel benchmark using cached query vectors; every failure remains in the report."""

import math
import platform
import time

from photo_organizer.search.retrieval import vector_search


def measure(state, cases, repetitions=10):
    if (
        not isinstance(cases, list)
        or not cases
        or type(repetitions) is not int
        or not 1 <= repetitions <= 100
    ):
        raise ValueError("provide query cases and 1..100 repetitions")
    samples = []
    for case in cases:
        for repeat in range(repetitions):
            started = time.perf_counter()
            error = None
            try:
                result = vector_search(state, **case)
                count = result["total"]
            except Exception as failure:
                # Benchmark failures are measurements, never silently omitted.
                error = type(failure).__name__
                count = None
            samples.append(
                {
                    "case": case,
                    "repeat": repeat,
                    "seconds": time.perf_counter() - started,
                    "error": error,
                    "returned": count,
                }
            )
    elapsed = sorted(r["seconds"] for r in samples)
    failures = sum(r["error"] is not None for r in samples)
    p95 = elapsed[max(0, math.ceil(len(elapsed) * 0.95) - 1)]
    distinct = len({(c.get("space_id"), c.get("text"), c.get("reference_id")) for c in cases})
    protocol = distinct >= 20 and repetitions >= 10
    return {
        "samples": samples,
        "failures": failures,
        "success_rate": 1 - failures / len(samples),
        "p95_seconds": p95,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "boundary": "cached-query vector retrieval, scope filtering, ranking, snapshot creation and first page; no model/agent latency",
        "gate": "unmeasured"
        if not protocol
        else "passed"
        if not failures and p95 <= 0.2
        else "failed",
    }
