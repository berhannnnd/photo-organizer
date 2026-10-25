"""Worker scheduling, checkpoints and recovery of durable items."""

import hashlib
import json
import os
import time
from pathlib import Path

from photo_organizer.core.errors import CapabilityError
from photo_organizer.search.selection import now
from photo_organizer.storage.catalog import connect, writer_lock

MODEL_JOBS = {"index", "review", "embed", "ocr", "faces"}


def run(state, task_id):
    try:
        with writer_lock(Path(state) / "job-locks" / task_id):
            return _run(state, task_id)
    except ValueError as error:
        if "another writer" not in str(error):
            raise
        return {"task_id": task_id, "status": "owned_by_another_worker"}


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
            changed = any(
                c.execute(
                    "SELECT revision FROM capability_configs WHERE role=?", (role,)
                ).fetchone()[0]
                != rev
                for role, rev in spec["capability_revisions"].items()
            )
            model = operation in MODEL_JOBS
            reached = (
                progress["seconds"] >= budget.get("max_seconds", float("inf"))
                or (
                    item["attempts"] == 0
                    and operation not in ("scan", "apply")
                    and progress.get("images", 0) >= budget.get("max_images", float("inf"))
                )
                or model
                and progress.get("requests", 0) >= budget.get("max_requests", float("inf"))
                or model
                and (progress.get("requests", 0) + 1) * budget.get("max_request_cost", 0)
                > budget.get("max_cost", float("inf"))
            )
            if changed or reached:
                error = {
                    "code": "version_conflict" if changed else "budget_exhausted",
                    "message": "Configuration changed"
                    if changed
                    else "Increase budget to resume; completed items are preserved",
                }
                c.execute(
                    "UPDATE jobs SET status='needs_input',owner=NULL,error=?,progress=?,updated=? WHERE id=?",
                    (json.dumps(error), json.dumps(progress), now(), task_id),
                )
                return
            c.execute(
                "UPDATE job_items SET status='running',attempts=attempts+1 WHERE job_id=? AND item_id=?",
                (task_id, item["item_id"]),
            )
            # Reserve before dispatch; a crash cannot silently erase possible request cost.
            if model:
                progress["requests"] = progress.get("requests", 0) + 1
            if operation not in ("scan", "apply") and item["attempts"] == 0:
                progress["images"] = progress.get("images", 0) + 1
            c.execute(
                "UPDATE jobs SET progress=?,updated=? WHERE id=?",
                (json.dumps(progress), now(), task_id),
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
            with writer_lock(Path(state) / "stage-locks" / stage):
                output = execute(state, operation, spec, payload)
        except Exception as e:
            error = {
                "code": e.code if isinstance(e, CapabilityError) else "operation_failed",
                "message": str(e)[:300]
                if isinstance(e, (CapabilityError, ValueError, OSError))
                else type(e).__name__,
                "retryable": isinstance(e, CapabilityError) and e.retryable,
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
            c.execute(
                "UPDATE jobs SET progress=?,updated=? WHERE id=?",
                (json.dumps(progress), now(), task_id),
            )
        if error and retry:
            # Short interruptible backoff: controls remain responsive.
            for _ in range(2 ** (item["attempts"] + 1) * 5):
                time.sleep(0.2)
                with connect(state) as c:
                    if c.execute("SELECT control FROM jobs WHERE id=?", (task_id,)).fetchone()[0]:
                        break
