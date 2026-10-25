"""Durable request reservations and cooperative job boundaries."""

import json
import time

from photo_organizer.search.selection import now
from photo_organizer.storage.catalog import connect


class JobBoundary(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def revisions(c, operation):
    roles = {
        "index": ["vision"],
        "review": ["vision"],
        "embed": ["image_text"],
        "ocr": ["ocr"],
        "faces": ["faces"],
    }.get(operation, [])
    if operation == "ocr":
        row = c.execute("SELECT config FROM capability_configs WHERE role='ocr'").fetchone()
        if row and json.loads(row[0])["protocol"] == "vision":
            roles = ["ocr", "vision"]
    return {
        role: (
            row[0]
            if (
                row := c.execute(
                    "SELECT revision FROM capability_configs WHERE role=?", (role,)
                ).fetchone()
            )
            else None
        )
        for role in roles
    }


class Admission:
    def __init__(
        self, state, task_id, item_id, operation, spec, progress, budget, started, previous
    ):
        self.state, self.task_id, self.item_id = state, task_id, item_id
        self.operation, self.spec, self.progress, self.budget = operation, spec, progress, budget
        self.started, self.previous = started, previous

    def _check(self, c):
        job = c.execute("SELECT control FROM jobs WHERE id=?", (self.task_id,)).fetchone()
        if job[0] in ("pause", "cancel"):
            raise JobBoundary(
                "paused" if job[0] == "pause" else "cancelled",
                "control_requested",
                "Stopped at an item/request boundary",
            )
        if revisions(c, self.operation) != self.spec["capability_revisions"]:
            raise JobBoundary(
                "needs_input", "version_conflict", "Configuration changed; resume with rebind=true"
            )
        self.progress["seconds"] = self.previous + time.monotonic() - self.started
        if self.progress["seconds"] >= self.budget.get("max_seconds", float("inf")):
            raise JobBoundary("needs_input", "budget_exhausted", "Time budget exhausted")

    def checkpoint(self):
        with connect(self.state) as c:
            self._check(c)

    def reserve(self, remote):
        with connect(self.state) as c:
            c.execute("BEGIN IMMEDIATE")
            self._check(c)
            charged = c.execute(
                "SELECT charged FROM job_items WHERE job_id=? AND item_id=?",
                (self.task_id, self.item_id),
            ).fetchone()[0]
            images = self.progress.get("images", 0) + (not charged)
            requests = self.progress.get("requests", 0) + remote
            if (
                images > self.budget.get("max_images", float("inf"))
                or requests > self.budget.get("max_requests", float("inf"))
                or requests * self.budget.get("max_request_cost", 0)
                > self.budget.get("max_cost", float("inf"))
            ):
                raise JobBoundary(
                    "needs_input",
                    "budget_exhausted",
                    "Increase budget to resume; completed items are preserved",
                )
            self.progress.update(images=images, requests=requests)
            c.execute(
                "UPDATE job_items SET charged=1 WHERE job_id=? AND item_id=?",
                (self.task_id, self.item_id),
            )
            c.execute(
                "UPDATE jobs SET progress=?,updated=? WHERE id=?",
                (json.dumps(self.progress), now(), self.task_id),
            )
