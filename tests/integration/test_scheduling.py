"""Provider admission across processes and durable spend boundaries."""

import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from photo_organizer.capabilities.registry import configure
from photo_organizer.capabilities.scheduling import provider_slot
from photo_organizer.core.errors import CapabilityError
from photo_organizer.runtime import jobs
from photo_organizer.runtime.context import admit, execution_context

from . import test_jobs_lifecycle


def occupy(config, queue):
    with provider_slot(config):
        queue.put(("start", os.getpid(), time.monotonic()))
        time.sleep(0.12)
        queue.put(("end", os.getpid(), time.monotonic()))


class SchedulingTests(unittest.TestCase):
    setUp = test_jobs_lifecycle.JobLifecycleTests.setUp
    tearDown = test_jobs_lifecycle.JobLifecycleTests.tearDown

    def test_process_slots_bound_concurrency(self):
        config = {"endpoint": "https://test/" + tempfile.mktemp(), "concurrency": 1}
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        processes = [ctx.Process(target=occupy, args=(config, queue)) for _ in range(3)]
        for process in processes:
            process.start()
        events = [queue.get(timeout=10) for _ in range(6)]
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        active = 0
        for kind, _, _ in sorted(events, key=lambda e: e[2]):
            active += 1 if kind == "start" else -1
            self.assertLessEqual(active, 1)
        queue.close()

    def test_foreground_waiter_precedes_background(self):
        config = {"endpoint": "https://test/" + tempfile.mktemp(), "concurrency": 1}
        order = []
        entered = threading.Event()

        def wait(name, background):
            with execution_context(background=background):
                entered.set()
                with provider_slot(config):
                    order.append(name)

        with provider_slot(config):
            fg = threading.Thread(target=wait, args=("foreground", False))
            fg.start()
            entered.wait(2)
            # Wait until the foreground ticket exists, rather than guessing scheduling latency.
            import hashlib
            from pathlib import Path

            root = (
                Path(tempfile.gettempdir())
                / ("photo-provider-" + str(os.getuid()))
                / hashlib.sha256(config["endpoint"].rstrip("/").encode()).hexdigest()
            )
            deadline = time.monotonic() + 2
            while not list(root.glob("waiting-*")) and time.monotonic() < deadline:
                time.sleep(0.01)
            bg = threading.Thread(target=wait, args=("background", True))
            bg.start()
        fg.join(3)
        bg.join(3)
        self.assertEqual(order, ["foreground", "background"])

    def test_cache_does_not_spend_budget(self):
        first = jobs.start(
            self.state, "quality", {"result_id": self.r["result_set_id"]}, background=False
        )["task_id"]
        jobs.run(self.state, first)
        second = jobs.start(
            self.state,
            "quality",
            {"result_id": self.r["result_set_id"]},
            {"max_images": 1, "max_requests": 1},
            False,
        )["task_id"]
        jobs.run(self.state, second)
        status = jobs.status(self.state, second)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["progress"]["requests"], 0)
        self.assertEqual(status["progress"]["images"], 0)

    def test_missing_role_requires_explicit_rebind(self):
        task = jobs.start(
            self.state, "embed", {"result_id": self.r["result_set_id"]}, background=False
        )["task_id"]
        jobs.run(self.state, task)
        configure(self.state, "image_text", {"protocol": "host"})
        with patch.object(jobs, "launch"):
            jobs.control(self.state, task, "resume")
        jobs.run(self.state, task)
        self.assertEqual(jobs.status(self.state, task)["error"]["code"], "version_conflict")

    def test_retry_counts_requests_but_one_image(self):
        task = jobs.start(
            self.state,
            "quality",
            {"result_id": self.r["result_set_id"]},
            {"max_images": 1, "max_requests": 2},
            False,
        )["task_id"]
        calls = []

        def action(*args):
            admit(True)
            calls.append(1)
            if len(calls) == 1:
                raise CapabilityError("rate_limited", "retry", True, retry_after=0)
            return {}

        with (
            patch("photo_organizer.runtime.job_actions.execute", action),
            patch("photo_organizer.runtime.runner.time.sleep"),
        ):
            jobs.run(self.state, task)
        status = jobs.status(self.state, task)
        self.assertEqual(status["counts"]["done"], 1)
        self.assertEqual(status["progress"]["images"], 1)
        self.assertEqual(status["progress"]["requests"], 2)
        self.assertEqual(status["status"], "needs_input")
