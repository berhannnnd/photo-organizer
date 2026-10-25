"""Candidate lineage, host vector spaces and explicit fallback contracts."""

import unittest
from unittest.mock import patch

from photo_organizer.capabilities.adapters.encoding import Encoder
from photo_organizer.core.errors import CapabilityError
from photo_organizer.search import results, retrieval, selection
from photo_organizer.vision import evidence

from . import test_composition


class RetrievalTests(unittest.TestCase):
    setUp = test_composition.CompositionTests.setUp
    tearDown = test_composition.CompositionTests.tearDown

    def host_index(self, model="model"):
        return retrieval.submit_vectors(
            self.state,
            self.all["result_set_id"],
            [
                {"file_id": r["id"], "hash": r["hash"], "vector": [1, n + 1]}
                for n, r in enumerate(self.all["items"])
            ],
            "joint",
            model,
            "revision-1",
            "cat",
            [1, 1],
        )["space_id"]

    def test_host_vectors_reference_and_space_isolation(self):
        space = self.host_index()
        other = self.host_index("different-model")
        self.assertNotEqual(space, other)
        r = retrieval.vector_search(self.state, space, reference_id=self.ids[0], top_k=1)
        self.assertEqual(r["items"][0]["id"], self.ids[0])
        self.assertEqual(r["context"]["scope_count"], 3)
        with self.assertRaises(CapabilityError):
            retrieval.vector_search(self.state, "missing-space", text="cat")
        with self.assertRaises(CapabilityError) as raised:
            Encoder({"protocol": "host"})
        self.assertEqual(raised.exception.code, "host_action_required")

    def test_search_and_combination_keep_unresolved_ancestor(self):
        space = self.host_index()
        first = retrieval.vector_search(self.state, space, reference_id=self.ids[0])
        second = retrieval.vector_search(
            self.state, space, text="cat", parent_id=first["result_set_id"]
        )
        self.assertEqual(len(second["context"]["requirements"]), 2)
        evidence.submit(
            self.state,
            second["result_set_id"],
            [
                {"file_id": r["id"], "hash": r["hash"], "verdict": "yes", "evidence": "visible cat"}
                for r in second["items"]
            ],
            {"kind": "host"},
            condition="cat",
        )
        refined = results.create(self.state, {"semantic": "cat"}, second["result_set_id"])
        self.assertEqual(refined["selection_kind"], "candidates")
        merged = selection.combine(self.state, [first["result_set_id"], refined["result_set_id"]])
        filtered = results.create(self.state, {"orientation": "landscape"}, merged["result_set_id"])
        self.assertEqual(filtered["selection_kind"], "candidates")

    def test_fallback_requires_explicit_opt_in(self):
        with patch.object(
            retrieval, "provider_for", side_effect=CapabilityError("missing_capability", "missing")
        ):
            with self.assertRaises(CapabilityError):
                retrieval.search(self.state, "cat")
            result = retrieval.search(self.state, "cat", allow_text_fallback=True)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["fallbacks"][0]["role"], "image_text")
        self.assertEqual(result["channel_coverage"], {"literal_text": 0})

    def test_stale_unanalyzed_members_cannot_be_selected(self):
        r = results.create(self.state, {"semantic": "cat"})
        from photo_organizer.storage.catalog import connect

        with connect(self.state) as c:
            c.execute("UPDATE files SET present=0 WHERE id=?", (self.ids[0],))
        with self.assertRaises(ValueError):
            selection.choose(self.state, r["result_set_id"], [self.ids[0]], verdicts=["unanalyzed"])

    def test_independent_description_space_and_partial_coverage(self):
        import hashlib

        from photo_organizer.search.embeddings import initialize, pack, register
        from photo_organizer.storage.catalog import connect

        class Provider:
            model = "test"
            digest = "1"
            endpoint = "local"

            def __init__(self, role):
                self.space = role

            def encode(self, text):
                return pack([1, 0] if self.space == "image_text" else [1, 0, 0])

        with connect(self.state) as c:
            initialize(c)
            c.execute(
                "INSERT INTO capability_configs VALUES('description_text','{}','v','available',NULL,'now')"
            )
            register(c, Provider("image_text"), pack([1, 0]))
            register(c, Provider("description_text"), pack([1, 0, 0]))
            first, second = self.all["items"][:2]
            c.execute(
                "INSERT INTO image_vectors VALUES(?,?,?)",
                ("image_text", first["hash"], pack([1, 0])),
            )
            c.execute(
                "UPDATE assets SET caption='cat portrait',vision_state='complete',vision_version='v1' WHERE hash=?",
                (second["hash"],),
            )
            c.execute(
                "INSERT INTO description_vectors VALUES(?,?,?,?,?)",
                (
                    "description_text",
                    second["hash"],
                    "v1",
                    hashlib.sha256(b"cat portrait").hexdigest(),
                    pack([1, 0, 0]),
                ),
            )
        with patch.object(
            retrieval,
            "provider_for",
            side_effect=lambda state, model, endpoint, role: Provider(role),
        ):
            result = retrieval.search(self.state, "cat", top_k=3)
            self.assertEqual(
                result["channel_coverage"], {"image": 1, "description": 1, "literal_text": 1}
            )
            self.assertEqual({r["id"] for r in result["items"]}, {first["id"], second["id"]})
            self.assertEqual(retrieval.search(self.state, "cat")["model_calls"], 0)
            with connect(self.state) as c:
                c.execute("UPDATE assets SET vision_version='v2' WHERE hash=?", (second["hash"],))
            self.assertEqual(
                retrieval.search(self.state, "cat")["channel_coverage"]["description"], 0
            )
