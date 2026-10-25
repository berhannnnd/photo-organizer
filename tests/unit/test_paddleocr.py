import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photo_organizer.capabilities.adapters.ocr import recognize
from photo_organizer.core.errors import CapabilityError


class PaddleOCRTests(unittest.TestCase):
    def invoke(self, item, code=0):
        response = {"errorCode": code, "result": {"ocrResults": [{"prunedResult": item}]}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image.jpg"
            path.write_bytes(b"test-image")
            with patch(
                "photo_organizer.capabilities.adapters.ocr.request", return_value=response
            ) as send:
                result = recognize({"protocol": "paddleocr"}, path)
                self.assertFalse(send.call_args.args[1]["useDocOrientationClassify"])
                self.assertFalse(send.call_args.args[1]["useDocUnwarping"])
                self.assertEqual(send.call_args.args[1]["fileType"], 1)
                return result

    def test_text_geometry_and_empty_image(self):
        result = self.invoke(
            {"rec_texts": ["订单123"], "rec_scores": [0.9], "rec_boxes": [[1, 2, 30, 40]]}
        )
        self.assertEqual(result["text"], "订单123")
        self.assertEqual(result["coordinate_system"], "input_pixels_xyxy")
        self.assertEqual(result["regions"][0]["box"], [1, 2, 30, 40])
        self.assertEqual(
            self.invoke({"rec_texts": [], "rec_scores": [], "rec_boxes": []})["text"], ""
        )

    def test_malformed_and_failed_responses(self):
        for item in (
            None,
            {},
            {"rec_texts": ["x"], "rec_scores": [], "rec_boxes": []},
            {"rec_texts": ["x"], "rec_scores": [float("nan")], "rec_boxes": [[1, 2, 3, 4]]},
        ):
            with self.subTest(item=item), self.assertRaises(CapabilityError):
                self.invoke(item)
        with self.assertRaises(CapabilityError):
            self.invoke({}, code=1)
