import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photo_organizer.library.ingest import scan
from photo_organizer.organizing.execution import apply
from photo_organizer.organizing.planning import plan
from photo_organizer.search.query import search
from photo_organizer.storage.catalog import connect
from photo_organizer.vision.indexing import index
from photo_organizer.vision.provider import ProviderError, validate_label
from photo_organizer.vision.semantic import enrich


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "input"
        self.root.mkdir()
        self.state = self.base / "state"
        exif = Image.Exif()
        exif[36867] = "2024:06:01 12:00:00"
        Image.new("RGB", (160, 100), "red").save(self.root / "cat.jpg", exif=exif)
        Image.new("RGB", (100, 160), "blue").save(self.root / "dog.jpg")
        scan(self.state, self.root)
        with connect(self.state) as c:
            for r in c.execute("SELECT * FROM files").fetchall():
                tag = Path(r["path"]).stem
                c.execute(
                    "UPDATE assets SET vision_state='complete',vision_version='test',caption=?,category='animal' WHERE hash=?",
                    (tag, r["hash"]),
                )
                c.execute("INSERT INTO tags VALUES(?,?)", (r["hash"], tag))

    def tearDown(self):
        self.tmp.cleanup()

    def test_incremental_duplicate_and_missing(self):
        self.assertEqual(scan(self.state, self.root)["cache_hits"], 2)
        (self.root / "duplicate.jpg").write_bytes((self.root / "cat.jpg").read_bytes())
        r = scan(self.state, self.root)
        self.assertEqual(r["files"], 3)
        self.assertEqual(r["unique_contents"], 2)
        (self.root / "dog.jpg").unlink()
        self.assertEqual(scan(self.state, self.root)["files"], 2)

    def test_bad_file_and_symlink_are_visible_errors(self):
        (self.root / "bad.jpg").write_bytes(b"broken")
        (self.root / "linked.jpg").symlink_to(self.root / "cat.jpg")
        r = scan(self.state, self.root)
        self.assertEqual(r["files"], 4)
        self.assertEqual(r["file_errors"], 2)

    def test_date_unknown_and_and_not(self):
        with connect(self.state) as c:
            r = search(c, {"all_tags": ["猫"], "not_tags": ["狗"]})
            self.assertEqual(r["total"], 0)
            self.assertEqual(r["judgments"]["unknown_or_unanalyzed"], 1)
            self.assertEqual(search(c, {"all_tags": ["cat", "dog"]})["total"], 0)
            self.assertEqual(
                search(c, {"date_from": "2024-06-01", "date_to": "2024-06-01"})["total"], 1
            )
            with self.assertRaises(ValueError):
                search(c, {"date_from": "2025-01-01", "date_to": "2024-01-01"})
        p = plan(self.state, {"group_by": "month"})
        self.assertEqual(p["groups"], {"2024/06": 1, "date-unknown": 1})

    def test_pending_not_excluded_as_negative(self):
        with connect(self.state) as c:
            c.execute("UPDATE assets SET vision_state='pending'")
            self.assertEqual(search(c, {"not_tags": ["dog"]})["total"], 0)

    def test_all_members_no_search_limit(self):
        for i in range(35):
            (self.root / f"dup{i}.jpg").write_bytes((self.root / "cat.jpg").read_bytes())
        scan(self.state, self.root)
        p = plan(
            self.state,
            {"group_by": "rules", "groups": [{"name": "cats", "where": {"all_tags": ["cat"]}}]},
        )
        self.assertEqual(p["selected"], 37)
        self.assertEqual(p["groups"]["cats"], 36)
        self.assertEqual(apply(self.state, p["plan_id"])["outcomes"]["memberships"], 37)

    def test_copy_and_idempotency_and_conflict(self):
        target = self.base / "out"
        p = plan(self.state, {}, target, "copy")
        r = apply(self.state, p["plan_id"])
        self.assertFalse(r["errors"])
        self.assertEqual(r["outcomes"]["written"], 2)
        self.assertEqual(apply(self.state, p["plan_id"])["outcomes"]["reused"], 2)
        next(target.rglob("*.jpg")).write_bytes(b"user edit")
        self.assertEqual(len(apply(self.state, p["plan_id"])["errors"]), 1)

    def test_source_changed(self):
        p = plan(self.state, {}, self.base / "out", "copy")
        (self.root / "cat.jpg").write_bytes(b"changed")
        r = apply(self.state, p["plan_id"])
        self.assertEqual(len(r["errors"]), 1)

    def test_paths_and_preexisting_target(self):
        with self.assertRaises(ValueError):
            plan(self.state, {}, self.root / "out", "copy")
        with self.assertRaises(ValueError):
            plan(self.state, {"group_by": "rules", "groups": [{"name": "../bad", "where": {}}]})
        out = self.base / "out"
        out.symlink_to(self.root, target_is_directory=True)
        p = plan(self.state, {}, out, "copy")
        self.assertEqual(len(apply(self.state, p["plan_id"])["errors"]), 2)

    def test_no_clobber_existing_same_bytes(self):
        p = plan(self.state, {}, self.base / "out", "copy")
        with connect(self.state) as c:
            row = c.execute(
                "SELECT * FROM actions WHERE plan_id=? LIMIT 1", (p["plan_id"],)
            ).fetchone()
        target = self.base / "out" / row["relative"]
        target.parent.mkdir(parents=True)
        target.write_bytes(Path(row["source"]).read_bytes())
        self.assertEqual(len(apply(self.state, p["plan_id"])["errors"]), 1)

    def test_recover_published_before_commit(self):
        p = plan(self.state, {}, self.base / "out", "copy")
        with connect(self.state) as c:
            row = c.execute(
                "SELECT * FROM actions WHERE plan_id=? LIMIT 1", (p["plan_id"],)
            ).fetchone()
            target = self.base / "out" / row["relative"]
            target.parent.mkdir(parents=True)
            tmp = target.parent / (".photo-organizer-" + row["id"] + ".tmp")
            tmp.write_bytes(Path(row["source"]).read_bytes())
            os.link(tmp, target)
            c.execute(
                "UPDATE actions SET status='running',output_hash=? WHERE id=?",
                (row["hash"], row["id"]),
            )
        result = apply(self.state, p["plan_id"])
        self.assertFalse(result["errors"])
        self.assertEqual(result["outcomes"]["recovered"], 1)

    def test_compression(self):
        p = plan(self.state, {"long_edge": 80, "quality": 70}, self.base / "out", "compress")
        self.assertFalse(apply(self.state, p["plan_id"])["errors"])
        for file in (self.base / "out").rglob("*.jpg"):
            with Image.open(file) as im:
                self.assertEqual(max(im.size), 80)

    def test_unknown_rule(self):
        with connect(self.state) as c:
            with self.assertRaises(ValueError):
                search(c, {"shell": "rm"})

    def test_model_schema_rejected(self):
        with self.assertRaises(ProviderError):
            validate_label(
                {"caption": "a", "tags": ["cat"], "category": "animal", "command": "touch"}
            )

    def test_semantic_cache_and_uncertain(self):
        class Fake:
            version = "fake"
            model = "fake"
            calls = 0

            def judge(self, path, condition):
                self.calls += 1
                return {"verdict": "uncertain", "evidence": "not visible"}, {"usage": {}}

        provider = Fake()
        r = enrich(self.state, provider, "朋友生日")
        self.assertEqual(r["coverage"]["uncertain"], 2)
        self.assertEqual(enrich(self.state, provider, "朋友生日")["completed_now"], 0)
        self.assertEqual(provider.calls, 2)
        with connect(self.state) as c:
            self.assertEqual(search(c, {"semantic": "朋友生日"})["total"], 0)

    def test_index_checkpoint_failed_only_retry(self):
        class Fake:
            version = "test"
            model = "fake"
            provider_id = "fake"
            url = "test"
            calls = 0

            def label(self, path):
                self.calls += 1
                if self.calls == 1:
                    raise ProviderError("HTTP 429")
                return {"caption": "猫", "tags": ["cat"], "category": "animal"}, {
                    "seconds": 0,
                    "image_bytes": 1,
                    "usage": {},
                }

        with connect(self.state) as c:
            c.execute("UPDATE assets SET vision_state='pending'")
        p = Fake()
        r = index(self.state, p, workers=1)
        self.assertEqual(r["failed_now"], 1)
        r = index(self.state, p, workers=1)
        self.assertEqual(r["completed_now"], 1)
        self.assertEqual(p.calls, 3)


if __name__ == "__main__":
    unittest.main()
