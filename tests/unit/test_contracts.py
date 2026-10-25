"""Public schema, corrections, paging and plan preflight behavior."""

import unittest

from jsonschema import Draft202012Validator
from PIL import Image, ImageCms

from photo_organizer.interfaces.discovery import operation_schema
from photo_organizer.interfaces.service import EXTENSIONS, OPERATIONS, dispatch
from photo_organizer.library import annotations, lifecycle
from photo_organizer.library.imaging import normalized
from photo_organizer.organizing import organization
from photo_organizer.organizing.execution import apply
from photo_organizer.organizing.planning import plan
from photo_organizer.search import results
from photo_organizer.storage.catalog import connect

from . import test_composition


class ContractTests(unittest.TestCase):
    setUp = test_composition.CompositionTests.setUp
    tearDown = test_composition.CompositionTests.tearDown

    def test_every_operation_has_valid_schema(self):
        for op in (*OPERATIONS, *EXTENSIONS):
            with self.subTest(operation=op):
                schema = operation_schema(None, op)["input_schema"]
                Draft202012Validator.check_schema(schema)
                self.assertFalse(schema["additionalProperties"])
        bad = dispatch(
            self.state,
            "job-start",
            {"operation": "quality", "arguments": {"result_id": "x"}, "background": "false"},
        )
        self.assertEqual(bad["error"]["code"], "invalid_request")
        self.assertEqual(
            dispatch(self.state, "search", {"rule": {"unknown_field": 1}})["status"], "failed"
        )

    def test_metadata_correction_preserves_original_and_drives_search(self):
        row = self.all["items"][0]
        annotations.correct(
            self.state,
            self.all["result_set_id"],
            [
                {
                    "file_id": row["id"],
                    "hash": row["hash"],
                    "changes": {
                        "taken": "2020-06-02",
                        "category": "family",
                        "tags": ["holiday"],
                        "latitude": 20,
                        "longitude": 30,
                    },
                }
            ],
        )
        with connect(self.state) as c:
            self.assertIsNone(
                c.execute("SELECT taken FROM assets WHERE hash=?", (row["hash"],)).fetchone()[0]
            )
        found = results.create(
            self.state,
            {
                "date_from": "2020-01-01",
                "category": "family",
                "all_tags": ["holiday"],
                "location_box": [19, 29, 21, 31],
            },
        )
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["id"], row["id"])
        self.assertEqual(
            annotations.history(self.state, self.all["result_set_id"], row["id"], limit=1)[
                "next_offset"
            ],
            1,
        )
        annotations.correct(
            self.state,
            self.all["result_set_id"],
            [{"file_id": row["id"], "hash": row["hash"], "changes": {"taken": None}}],
        )
        self.assertEqual(results.create(self.state, {"date_to": "2020-12-31"})["total"], 0)
        self.assertEqual(
            results.create(self.state, {"date_basis": "import", "date_from": "2000-01-01"})[
                "total"
            ],
            3,
        )

    def test_bounded_group_pages_and_collision_preflight(self):
        group = organization.propose(
            self.state, self.all["result_set_id"], [{"path": ["custom"], "ids": self.ids}]
        )
        page = organization.group_detail(
            self.state, group["group_spec_id"], limit=1, group="custom"
        )
        self.assertEqual(page["items"], self.ids[:1])
        self.assertEqual(page["next_offset"], 1)
        target = self.base / "out"
        first = plan(self.state, {"result_set_id": self.all["result_set_id"]}, str(target), "copy")
        apply(self.state, first["plan_id"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            plan(self.state, {"result_set_id": self.all["result_set_id"]}, str(target), "copy")

    def test_offline_snapshot_rejected_and_nested_roots_explicit(self):
        lifecycle.synchronize(self.state, str(self.root))
        (self.root / "nested").mkdir()
        with self.assertRaisesRegex(ValueError, "overlapping"):
            lifecycle.synchronize(self.state, str(self.root / "nested"))
        with connect(self.state) as c:
            c.execute("UPDATE roots SET status='offline' WHERE path=?", (str(self.root),))
        self.assertEqual(
            results.page(self.state, self.all["result_set_id"])["unavailable_members"], 3
        )
        with self.assertRaisesRegex(ValueError, "offline"):
            plan(self.state, {"result_set_id": self.all["result_set_id"]})

    def test_color_normalization_and_transparency(self):
        image = Image.new("RGB", (3, 3), "red")
        image.info["icc_profile"] = ImageCms.ImageCmsProfile(
            ImageCms.createProfile("sRGB")
        ).tobytes()
        converted = normalized(image)
        self.assertEqual(converted.mode, "RGB")
        self.assertEqual(converted.getpixel((0, 0)), (255, 0, 0))
        transparent = Image.new("RGBA", (3, 3), (0, 0, 0, 0))
        self.assertEqual(normalized(transparent).getpixel((0, 0)), (255, 255, 255))

    def test_dynamic_recipe_is_explicit_and_snapshot_does_not_expand(self):
        from photo_organizer.library import recipes

        dynamic = recipes.save(
            self.state,
            "landscapes",
            rule={"orientation": "landscape"},
            preference="Prefer bright images",
        )
        fixed = recipes.save(self.state, "chosen", result_id=self.all["result_set_id"])
        Image.new("RGB", (50, 25), "blue").save(self.root / "new.jpg")
        lifecycle.synchronize(self.state, str(self.root))
        self.assertEqual(recipes.materialize(self.state, dynamic["recipe_id"])["total"], 4)
        self.assertEqual(recipes.materialize(self.state, fixed["recipe_id"])["total"], 3)
        with self.assertRaisesRegex(ValueError, "version"):
            recipes.save(self.state, "edited", rule={}, recipe_id=dynamic["recipe_id"])
        changed = recipes.save(
            self.state, "edited", rule={}, recipe_id=dynamic["recipe_id"], expected_version=1
        )
        self.assertEqual(changed["version"], 2)

    def test_coverage_includes_unanalyzed_scope_and_metadata_snapshot_changes(self):
        from photo_organizer.search.coverage import inspect

        unknown = results.create(self.state, {"semantic": "cat"})
        report = inspect(self.state, unknown["result_set_id"], "cat")
        self.assertEqual(report["scope_files"], 3)
        self.assertEqual(report["criterion_verdicts"], {"unanalyzed": 3})
        row = self.all["items"][0]
        annotations.correct(
            self.state,
            self.all["result_set_id"],
            [{"file_id": row["id"], "hash": row["hash"], "changes": {"category": "family"}}],
        )
        page = results.page(self.state, self.all["result_set_id"])
        item = next(r for r in page["items"] if r["id"] == row["id"])
        self.assertTrue(item["evidence_changed"])
        self.assertIsNone(item["snapshot_evidence"]["category"])
