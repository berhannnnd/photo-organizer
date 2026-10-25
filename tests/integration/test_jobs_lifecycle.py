import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photo_organizer.library import lifecycle
from photo_organizer.organizing.planning import plan
from photo_organizer.runtime import jobs
from photo_organizer.search import results
from photo_organizer.storage.catalog import connect


class JobLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "photos"
        self.root.mkdir()
        self.state = self.base / "state"
        for i in range(3):
            Image.new("RGB", (20 + i, 10), "red").save(self.root / f"{i}.jpg")
        lifecycle.synchronize(self.state, str(self.root))
        self.r = results.create(self.state, {})

    def tearDown(self):
        self.tmp.cleanup()

    def test_budget_resume_and_durable_apply_receipts(self):
        t = jobs.start(
            self.state, "quality", {"result_id": self.r["result_set_id"]}, {"max_images": 1}, False
        )["task_id"]
        jobs.run(self.state, t)
        s = jobs.status(self.state, t)
        self.assertEqual(s["status"], "needs_input")
        self.assertEqual(s["counts"]["done"], 1)
        with patch.object(jobs, "launch"):
            jobs.control(self.state, t, "resume", {"max_images": 10})
        jobs.run(self.state, t)
        self.assertEqual(jobs.status(self.state, t)["status"], "completed")
        p = plan(
            self.state, {"result_set_id": self.r["result_set_id"]}, str(self.base / "out"), "copy"
        )
        t = jobs.start(self.state, "apply", {"plan_id": p["plan_id"]}, background=False)["task_id"]
        jobs.run(self.state, t)
        s = jobs.status(self.state, t)
        self.assertEqual(s["status"], "completed")
        self.assertTrue(s["result"]["collection_id"])
        self.assertEqual(len(list((self.base / "out").rglob("*.jpg"))), 3)

    def test_cancel_acknowledged_inflight_stops_dispatch(self):
        t = jobs.start(
            self.state, "quality", {"result_id": self.r["result_set_id"]}, background=False
        )["task_id"]
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def execute(*a):
            calls.append(a)
            entered.set()
            release.wait(3)
            return {"ok": True}

        with patch("photo_organizer.runtime.job_actions.execute", execute):
            worker = threading.Thread(target=jobs.run, args=(self.state, t))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                ack = jobs.control(self.state, t, "cancel")
                self.assertEqual(ack["status"], "cancelling")
            finally:
                release.set()
                worker.join(3)
        s = jobs.status(self.state, t)
        self.assertEqual(s["status"], "cancelled")
        self.assertEqual(len(calls), 1)

    def test_missing_capability_and_dedup(self):
        a = jobs.start(
            self.state,
            "review",
            {"result_id": self.r["result_set_id"], "condition": "red"},
            background=False,
        )
        b = jobs.start(
            self.state,
            "review",
            {"result_id": self.r["result_set_id"], "condition": "red"},
            background=False,
        )
        self.assertEqual(a["task_id"], b["task_id"])
        jobs.run(self.state, a["task_id"])
        self.assertEqual(jobs.status(self.state, a["task_id"])["status"], "needs_input")

    def test_rename_keeps_identity_offline_does_not_delete(self):
        first = next(x for x in self.r["items"] if x["path"].endswith("0.jpg"))
        (self.root / "0.jpg").rename(self.root / "renamed.jpg")
        lifecycle.synchronize(self.state, str(self.root))
        r = results.page(self.state, self.r["result_set_id"])
        self.assertEqual(r["stale_members"], 0)
        current = next(x for x in r["items"] if x["id"] == first["id"])
        self.assertTrue(current["current_path"].endswith("renamed.jpg"))
        moved = self.base / "offline"
        self.root.rename(moved)
        with self.assertRaises(ValueError):
            lifecycle.synchronize(self.state, str(self.root))
        self.assertEqual(results.create(self.state, {})["total"], 0)
        with connect(self.state) as c:
            self.assertEqual(
                c.execute("SELECT count(*) FROM files WHERE present=1").fetchone()[0], 3
            )
        moved.rename(self.root)
        lifecycle.synchronize(self.state, str(self.root))
        self.assertEqual(results.create(self.state, {})["total"], 3)

    def test_partial_scan_failure_does_not_mark_missing(self):

        def broken(*args, **kwargs):
            yield str(self.root), [], ["0.jpg"]
            raise PermissionError("denied")

        with patch("photo_organizer.library.ingest.os.walk", broken):
            with self.assertRaises(PermissionError):
                lifecycle.synchronize(self.state, str(self.root))
        self.assertEqual(results.create(self.state, {})["total"], 3)

    def test_detached_worker_completes(self):
        t = jobs.start(self.state, "quality", {"result_id": self.r["result_set_id"]})["task_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            s = jobs.status(self.state, t)
            if s["status"] == "completed":
                break
            time.sleep(0.05)
        self.assertEqual(s["status"], "completed")


if __name__ == "__main__":
    unittest.main()
