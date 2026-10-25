"""Durable bounded jobs with process-independent controls and resumable item receipts."""

import json
import subprocess
import sys
import uuid
from pathlib import Path

from photo_organizer.search.selection import members, now
from photo_organizer.storage.catalog import connect, writer_lock

ALLOWED = {"index", "review", "embed", "ocr", "quality", "faces", "scan", "apply"}
MODEL_JOBS = {"index", "review", "embed", "ocr", "faces"}


def status(state, task_id=None, limit=50, offset=0):
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        raise ValueError("invalid pagination")
    with connect(state) as c:
        if task_id is None:
            return {
                "tasks": [
                    dict(r)
                    for r in c.execute(
                        "SELECT id,operation,status,created,updated FROM jobs ORDER BY created DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    )
                ]
            }
        row = c.execute("SELECT * FROM jobs WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError("unknown task")
        data = dict(row)
        for key in ("arguments", "progress", "result", "error", "budget"):
            data[key] = json.loads(data[key]) if data[key] else None
        data["items"] = [
            {**dict(r), "result": json.loads(r["result"]) if r["result"] else None}
            for r in c.execute(
                "SELECT * FROM job_items WHERE job_id=? ORDER BY item_id LIMIT ? OFFSET ?",
                (task_id, limit, offset),
            )
        ]
        data["counts"] = dict(
            c.execute(
                "SELECT status,count(*) FROM job_items WHERE job_id=? GROUP BY status", (task_id,)
            )
        )
        total = sum(data["counts"].values())
        data["total"] = total
        data["next_offset"] = offset + limit if offset + limit < total else None
        data["in_flight"] = data["counts"].get("running", 0)
        return data


def launch(state, task_id):
    # Worker survives host sessions; lock ownership is held by the worker itself.
    log = Path(state).resolve() / "workers.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "photo_organizer.runtime.worker",
                "--state",
                str(Path(state).resolve()),
                "--task",
                task_id,
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
            close_fds=True,
        )

    import threading

    threading.Thread(target=process.wait, daemon=True).start()


def start(state, operation, arguments, budget=None, background=True):
    if operation not in ALLOWED or not isinstance(arguments, dict):
        raise ValueError("unsupported job operation")
    allowed = (
        {"result_id", "condition"}
        if operation == "review"
        else {"root", "verify"}
        if operation == "scan"
        else {"plan_id"}
        if operation == "apply"
        else {"result_id"}
    )
    if set(arguments) - allowed:
        raise ValueError("invalid job arguments")
    if operation == "review" and (
        not isinstance(arguments.get("condition"), str)
        or not 1 <= len(arguments["condition"].strip()) <= 2000
    ):
        raise ValueError("review condition required")
    budget = validate_budget(budget or {})
    if type(background) is not bool:
        raise ValueError("background must be boolean")
    with writer_lock(Path(state) / "jobs-lock"), connect(state) as c:
        roles = {
            "index": ["vision"],
            "review": ["vision"],
            "embed": ["image_text"],
            "ocr": ["ocr", "vision"],
            "faces": ["faces"],
        }.get(operation, [])
        revisions = {
            r["role"]: r["revision"]
            for r in c.execute("SELECT role,revision FROM capability_configs")
            if r["role"] in roles
        }
        spec = {**arguments, "capability_revisions": revisions}
        key = json.dumps([operation, spec], sort_keys=True)
        for existing in c.execute(
            "SELECT id,operation,arguments FROM jobs WHERE status IN ('queued','running','pausing')"
        ):
            if (
                json.dumps(
                    [existing["operation"], json.loads(existing["arguments"])], sort_keys=True
                )
                == key
            ):
                return {"task_id": existing["id"], "deduplicated": True}
        if operation not in ("scan", "apply"):
            if not arguments.get("result_id"):
                raise ValueError("result_id required to freeze job scope")
            rows = members(c, arguments["result_id"])
            items = (
                {r["hash"]: r for r in rows}
                if operation in MODEL_JOBS or operation == "quality"
                else {str(r["file_id"]): r for r in rows}
            )
        elif operation == "apply":
            if not c.execute(
                "SELECT 1 FROM plans WHERE id=?", (arguments.get("plan_id"),)
            ).fetchone():
                raise ValueError("unknown plan")
            items = {
                r["id"]: {"action_id": r["id"]}
                for r in c.execute(
                    "SELECT id FROM actions WHERE plan_id=?", (arguments["plan_id"],)
                )
            }
        else:
            if not isinstance(arguments.get("root"), str):
                raise ValueError("root required")
            items = {"scan": {"root": arguments["root"]}}
        tid = uuid.uuid4().hex
        timestamp = now()
        c.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                operation,
                json.dumps(spec),
                "queued",
                timestamp,
                timestamp,
                None,
                None,
                json.dumps({"completed": 0, "requests": 0, "images": 0, "seconds": 0}),
                None,
                None,
                json.dumps(budget),
            ),
        )
        c.executemany(
            "INSERT INTO job_items(job_id,item_id,status,result) VALUES(?,?,?,?)",
            [(tid, str(k), "pending", json.dumps({"input": v})) for k, v in items.items()],
        )
    if background:
        launch(state, tid)
    return {"task_id": tid, "status": "queued", "total": len(items), "background": background}


def validate_budget(budget):
    if not isinstance(budget, dict) or set(budget) - {
        "max_images",
        "max_requests",
        "max_seconds",
        "max_cost",
        "max_request_cost",
    }:
        raise ValueError("unknown budget fields")
    if any(type(v) not in (int, float) or not 0 < v < 1e12 for v in budget.values()):
        raise ValueError("budgets must be positive finite numbers")
    if any(type(budget[k]) is not int for k in ("max_images", "max_requests") if k in budget):
        raise ValueError("image/request limits must be integers")
    if "max_cost" in budget and "max_request_cost" not in budget:
        raise ValueError(
            "unknown model pricing: use image/request caps or supply an explicit conservative max_request_cost"
        )
    return budget


def control(state, task_id, action, budget=None, rebind=False):
    if action not in ("pause", "cancel", "resume", "retry"):
        raise ValueError("action must be pause, cancel, resume or retry")
    with connect(state) as c:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT status FROM jobs WHERE id=?", (task_id,)).fetchone()
        if not r:
            raise ValueError("unknown task")
        if budget is not None:
            c.execute(
                "UPDATE jobs SET budget=? WHERE id=?",
                (json.dumps(validate_budget(budget)), task_id),
            )
        if action in ("pause", "cancel"):
            target = "pausing" if action == "pause" else "cancelling"
            if r[0] in ("queued", "paused", "needs_input", "cancelled", "failed", "partial_failed"):
                target = "paused" if action == "pause" else "cancelled"
            if r[0] == "completed":
                raise ValueError("completed task has no running work")
            c.execute(
                "UPDATE jobs SET control=?,status=?,updated=? WHERE id=?",
                (action, target, now(), task_id),
            )
        else:
            if rebind:
                job = c.execute(
                    "SELECT operation,arguments FROM jobs WHERE id=?", (task_id,)
                ).fetchone()
                spec = json.loads(job["arguments"])
                roles = {
                    "index": ["vision"],
                    "review": ["vision"],
                    "embed": ["image_text"],
                    "ocr": ["ocr", "vision"],
                    "faces": ["faces"],
                }.get(job["operation"], [])
                spec["capability_revisions"] = {
                    x["role"]: x["revision"]
                    for x in c.execute("SELECT role,revision FROM capability_configs")
                    if x["role"] in roles
                }
                c.execute("UPDATE jobs SET arguments=? WHERE id=?", (json.dumps(spec), task_id))
                if job["operation"] in MODEL_JOBS:
                    c.execute(
                        "UPDATE job_items SET status='pending',attempts=0 WHERE job_id=?",
                        (task_id,),
                    )
                    c.execute(
                        "UPDATE jobs SET progress=? WHERE id=?",
                        (
                            json.dumps({"completed": 0, "requests": 0, "images": 0, "seconds": 0}),
                            task_id,
                        ),
                    )
            if r[0] in ("running", "pausing", "cancelling"):
                raise ValueError(
                    "wait for in-flight work or explicitly recover an interrupted worker"
                )
            if r[0] == "completed":
                return {"task_id": task_id, "status": "completed"}
            if action == "retry":
                c.execute(
                    "UPDATE job_items SET status='pending',error=NULL,attempts=0 WHERE job_id=? AND status='failed'",
                    (task_id,),
                )
            c.execute(
                "UPDATE jobs SET control=NULL,status='queued',error=NULL,updated=? WHERE id=?",
                (now(), task_id),
            )
    if action in ("resume", "retry"):
        launch(state, task_id)
    return {
        "task_id": task_id,
        "control": action,
        "status": target if action in ("pause", "cancel") else "queued",
    }


def recover(state, task_id):
    with writer_lock(Path(state) / "job-locks" / task_id), connect(state) as c:
        row = c.execute("SELECT status FROM jobs WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError("unknown task")
        if row[0] in ("running", "pausing", "cancelling"):
            c.execute(
                "UPDATE jobs SET status='paused',owner=NULL,updated=? WHERE id=?", (now(), task_id)
            )
            c.execute(
                "UPDATE job_items SET status='pending' WHERE job_id=? AND status='running'",
                (task_id,),
            )
    return {
        "task_id": task_id,
        "next_action": "resume; completed actions are reconciled, not replayed blindly",
    }


def run(state, task_id):
    """Compatibility entry for in-process worker tests and explicit runners."""
    from .runner import run as run_worker

    return run_worker(state, task_id)
