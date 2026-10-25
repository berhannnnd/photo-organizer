"""Worker scheduling, checkpoints and recovery of durable items."""

import hashlib
import json
import os
import time
from pathlib import Path

from photo_organizer.core.errors import CapabilityError
from photo_organizer.runtime.admission import Admission, JobBoundary
from photo_organizer.runtime.context import execution_context
from photo_organizer.search.selection import now
from photo_organizer.storage.catalog import connect, writer_lock

MODEL_JOBS = {"index", "review", "embed", "ocr", "faces"}


def run(state, task_id):
    try:
        with writer_lock(Path(state) / "job-locks" / task_id):
            return _run(state, task_id)
    except ValueError as error:
        if "another writer" not in str(error):
            with connect(state) as c:
                c.execute(
                    "UPDATE jobs SET status='failed',owner=NULL,error=?,updated=? WHERE id=?",
                    (
                        json.dumps({"code": "worker_failed", "message": type(error).__name__}),
                        now(),
                        task_id,
                    ),
                )
            raise
        return {"task_id": task_id, "status": "owned_by_another_worker"}
    except Exception as error:
        with connect(state) as c:
            c.execute(
                "UPDATE jobs SET status='failed',owner=NULL,error=?,updated=? WHERE id=?",
                (
                    json.dumps({"code": "worker_failed", "message": type(error).__name__}),
                    now(),
                    task_id,
                ),
            )
            c.execute(
                "UPDATE job_items SET status='pending' WHERE job_id=? AND status='running'",
                (task_id,),
            )
        raise


def _run(state, task_id):
    from photo_organizer.runtime.job_actions import execute

    with connect(state) as c:
        c.execute("BEGIN IMMEDIATE")
        job = c.execute("SELECT * FROM jobs WHERE id=?", (task_id,)).fetchone()
        if not job or job["status"] not in ("queued", "running"):
            return
        spec = json.loads(job["arguments"])
        progress = json.loads(job["progress"])
        budget = json.loads(job["budget"])
        operation = job["operation"]
        c.execute(
            "UPDATE jobs SET status='running',owner=?,updated=? WHERE id=?",
            (str(os.getpid()), now(), task_id),
        )
        c.execute(
            "UPDATE job_items SET status='pending' WHERE job_id=? AND status='running'", (task_id,)
        )
    started = time.monotonic()
    previous_seconds = progress.get("seconds", 0)
    while True:
        with connect(state) as c:
            c.execute("BEGIN IMMEDIATE")
            job = c.execute("SELECT * FROM jobs WHERE id=?", (task_id,)).fetchone()
            progress["seconds"] = previous_seconds + time.monotonic() - started
            progress["time_budget_overrun_seconds"] = max(
                0, progress["seconds"] - budget.get("max_seconds", float("inf"))
            )
            if job["control"] in ("pause", "cancel"):
                state_name = "paused" if job["control"] == "pause" else "cancelled"
                c.execute(
                    "UPDATE jobs SET status=?,owner=NULL,progress=?,updated=? WHERE id=?",
                    (state_name, json.dumps(progress), now(), task_id),
                )
                return
            item = c.execute(
                "SELECT * FROM job_items WHERE job_id=? AND status='pending' ORDER BY item_id LIMIT 1",
                (task_id,),
            ).fetchone()
            if not item:
                failed = c.execute(
                    "SELECT count(*) FROM job_items WHERE job_id=? AND status='failed'", (task_id,)
                ).fetchone()[0]
                final = "partial_failed" if failed else "completed"
                final_result = {}
                if operation == "apply":
                    from photo_organizer.organizing.organization import record_collection

                    plan = c.execute(
                        "SELECT * FROM plans WHERE id=?", (spec["plan_id"],)
                    ).fetchone()
                    cid, rid = record_collection(c, plan)
                    final_result = {"collection_id": cid, "result_set_id": rid}
                c.execute(
                    "UPDATE jobs SET status=?,owner=NULL,progress=?,result=?,updated=? WHERE id=?",
                    (final, json.dumps(progress), json.dumps(final_result), now(), task_id),
                )
                return
            c.execute(
                "UPDATE job_items SET status='running',attempts=attempts+1 WHERE job_id=? AND item_id=?",
                (task_id, item["item_id"]),
            )
        payload = json.loads(item["result"])["input"]
        error = None
        try:
            stage = hashlib.sha256(
                json.dumps(
                    [
                        operation,
                        payload.get("hash"),
                        spec.get("condition"),
                        spec.get("capability_revisions"),
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            admission = Admission(
                state,
                task_id,
                item["item_id"],
                operation,
                spec,
                progress,
                budget,
                started,
                previous_seconds,
            )
            with execution_context(
                background=True,
                admission=admission.reserve,
                checkpoint=admission.checkpoint,
                commit=admission._check,
            ):
                admission.checkpoint()
                with writer_lock(Path(state) / "stage-locks" / stage):
                    output = execute(state, operation, spec, payload)
        except JobBoundary as boundary:
            with connect(state) as c:
                c.execute(
                    "UPDATE job_items SET status='pending',attempts=max(0,attempts-?) WHERE job_id=? AND item_id=?",
                    (int(not admission.admitted), task_id, item["item_id"]),
                )
                c.execute(
                    "UPDATE jobs SET status=?,owner=NULL,error=?,progress=?,updated=? WHERE id=?",
                    (
                        boundary.status,
                        json.dumps({"code": boundary.code, "message": str(boundary)}),
                        json.dumps(progress),
                        now(),
                        task_id,
                    ),
                )
            return
        except Exception as e:
            error = {
                "code": e.code
                if isinstance(e, CapabilityError)
                else "stage_busy"
                if isinstance(e, ValueError) and "another writer" in str(e)
                else "operation_failed",
                "message": str(e)[:300]
                if isinstance(e, (CapabilityError, ValueError, OSError))
                else type(e).__name__,
                "retryable": (isinstance(e, CapabilityError) and e.retryable)
                or (isinstance(e, ValueError) and "another writer" in str(e)),
                "retry_after": getattr(e, "retry_after", None),
            }
            output = None
        with connect(state) as c:
            if error:
                retry = error["retryable"] and item["attempts"] < 2
                c.execute(
                    "UPDATE job_items SET status=?,error=? WHERE job_id=? AND item_id=?",
                    ("pending" if retry else "failed", json.dumps(error), task_id, item["item_id"]),
                )
                if error["code"] in (
                    "missing_capability",
                    "unverified_capability",
                    "authentication_failed",
                    "authentication_required",
                    "permission_denied",
                    "version_conflict",
                    "host_action_required",
                ):
                    c.execute(
                        "UPDATE job_items SET status='pending' WHERE job_id=? AND item_id=?",
                        (task_id, item["item_id"]),
                    )
                    c.execute(
                        "UPDATE jobs SET status='needs_input',owner=NULL,error=?,updated=? WHERE id=?",
                        (json.dumps(error), now(), task_id),
                    )
                    return
            else:
                c.execute(
                    "UPDATE job_items SET status='done',result=?,error=NULL WHERE job_id=? AND item_id=?",
                    (json.dumps({"input": payload, "output": output}), task_id, item["item_id"]),
                )
                progress["completed"] = progress.get("completed", 0) + 1
                for key, value in output.get("usage", {}).items():
                    if type(value) in (int, float):
                        progress.setdefault("usage", {})[key] = (
                            progress.get("usage", {}).get(key, 0) + value
                        )
            c.execute(
                "UPDATE jobs SET progress=?,updated=? WHERE id=?",
                (json.dumps(progress), now(), task_id),
            )
        if error and retry:
            # Short interruptible backoff: controls remain responsive.
            delay = max(2 ** (item["attempts"] + 1), error.get("retry_after") or 0)
            for _ in range(int(delay * 5) + 1):
                time.sleep(0.2)
                try:
                    admission.checkpoint()
                except JobBoundary:
                    break
