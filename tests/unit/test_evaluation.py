import unittest

from photo_organizer.evaluation.quality import score


class EvaluationTests(unittest.TestCase):
    def test_missing_predictions_are_false_negatives_and_no_fake_perfect_precision(self):
        truth = {
            "scope_hashes": ["a", "b", "c"],
            "queries": [
                {
                    "id": "q1",
                    "group": "subject",
                    "labels": {"a": "yes", "b": "no", "c": "disputed"},
                },
                {"id": "q2", "group": "relation", "labels": {"a": "yes", "b": "yes", "c": "no"}},
            ],
        }
        report = score(truth, {"q1": ["a", "a", "b", "c"]})
        self.assertEqual(report["queries"][0]["precision"], 0.5)
        self.assertEqual(report["queries"][0]["disputed_returned"], 1)
        self.assertEqual(report["queries"][1]["fn"], 2)
        self.assertIsNone(report["queries"][1]["precision"])
        self.assertEqual(report["gate"], "unmeasured")
        truth["queries"][0]["labels"].pop("c")
        with self.assertRaises(ValueError):
            score(truth, {})
