import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photo_organizer.library.ingest import scan
from photo_organizer.organizing import organization
from photo_organizer.organizing.execution import apply
from photo_organizer.organizing.planning import plan
from photo_organizer.search import embeddings, results, selection
from photo_organizer.storage.catalog import connect
from photo_organizer.vision import evidence


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "photos"
        self.root.mkdir()
        self.state = self.base / "state"
        for i, color in enumerate(("red", "blue", "green")):
            Image.new("RGB", (40 + i, 20), color).save(self.root / f"{i}.jpg")
        scan(self.state, self.root)
        self.all = results.create(self.state, {})
        self.ids = [r["id"] for r in self.all["items"]]

    def tearDown(self):
        self.tmp.cleanup()

    def test_selection_sets_scope_and_order(self):
        a = selection.choose(self.state, self.all["result_set_id"], self.ids[:2])
        b = selection.choose(self.state, self.all["result_set_id"], self.ids[1:])
        self.assertEqual(
            selection.combine(self.state, [a["result_set_id"], b["result_set_id"]])["total"], 3
        )
        self.assertEqual(
            selection.combine(self.state, [a["result_set_id"], b["result_set_id"]], "intersection")[
                "total"
            ],
            1,
        )
        r = selection.choose(self.state, self.all["result_set_id"], self.ids[::-1], "order")
        self.assertEqual([i["id"] for i in r["items"]], self.ids[::-1])
        with self.assertRaises(ValueError):
            selection.choose(self.state, a["result_set_id"], [self.ids[-1]])

    def test_review_can_prove_original_retrieval_but_not_unrelated_conditions(self):
        class Fake:
            space = "s"
            model = "m"
            digest = "d"
            endpoint = "local"

            def __init__(self, *args):
                pass

            def encode(self, value):
                return embeddings.pack([1, 2])

        with patch.object(embeddings, "Ollama", Fake):
            embeddings.index(self.state)
            r = embeddings.search(self.state, "cat", top_k=2)
        records = [
            {
                "file_id": x["id"],
                "hash": x["hash"],
                "verdict": "yes",
                "evidence": "test visible evidence",
            }
            for x in r["items"]
        ]
        evidence.submit(self.state, r["result_set_id"], records, {"kind": "host"}, condition="cat")
        child = results.create(self.state, {"semantic": "cat"}, r["result_set_id"])
        self.assertEqual(child["selection_kind"], "evidence_matches")
        self.assertEqual(child["context"]["coverage"], "ranked_subset")
        self.assertEqual(plan(self.state, {"result_set_id": child["result_set_id"]})["selected"], 2)
        unrelated = results.create(self.state, {"orientation": "landscape"}, r["result_set_id"])
        self.assertEqual(unrelated["selection_kind"], "candidates")
        with self.assertRaises(ValueError):
            evidence.submit(
                self.state,
                r["result_set_id"],
                records,
                {"kind": "host"},
                condition="cat",
                expected_version="stale",
            )

    def test_unknown_and_unanalyzed_user_correction(self):
        rid = self.all["result_set_id"]
        row = self.all["items"][0]
        self.assertEqual(
            results.create(self.state, {"semantic": "red"})["judgments"], {"unanalyzed": 3}
        )
        version = evidence.submit(
            self.state,
            rid,
            [
                {
                    "file_id": row["id"],
                    "hash": row["hash"],
                    "verdict": "uncertain",
                    "evidence": "unclear",
                }
            ],
            {"kind": "host"},
            "red",
        )["condition_version"]
        r = results.create(self.state, {"semantic": "red"}, rid)
        self.assertEqual(r["judgments"], {"unknown": 1, "unanalyzed": 2})
        evidence.submit(
            self.state,
            rid,
            [
                {
                    "file_id": row["id"],
                    "hash": row["hash"],
                    "verdict": "yes",
                    "evidence": "user confirmed",
                }
            ],
            {"kind": "user"},
            "red",
            version,
        )
        self.assertEqual(results.create(self.state, {"semantic": "red"}, rid)["total"], 1)

    def test_image_crop_and_group_export_collection(self):
        rid = self.all["result_set_id"]
        pic = evidence.image(self.state, rid, self.ids[0], crop=[0, 0, 10, 10])
        with Image.open(io.BytesIO(base64.b64decode(pic["data"]))) as im:
            self.assertEqual(im.size, (10, 10))
        group = organization.propose(
            self.state, rid, [{"path": ["custom", "trip"], "ids": self.ids[:2]}]
        )
        task = plan(
            self.state,
            {
                "result_set_id": rid,
                "group_spec_id": group["group_spec_id"],
                "name_template": "{original}-{id}",
            },
            str(self.base / "out"),
            "copy",
        )
        done = apply(self.state, task["plan_id"])
        self.assertFalse(done["errors"])
        col = organization.collection(self.state, done["collection_id"], group="custom/trip")
        self.assertEqual(results.page(self.state, col["result_set_id"])["total"], 2)
        self.assertEqual(
            organization.plan_detail(self.state, task["plan_id"])["states"], {"done": 3}
        )

    def test_migration_reopens_and_no_future_version(self):
        with connect(self.state) as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 3)
        with connect(self.state) as c:
            c.execute("PRAGMA user_version=999")
        with self.assertRaises(ValueError):
            with connect(self.state):
                pass


if __name__ == "__main__":
    unittest.main()
