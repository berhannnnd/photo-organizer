"""Native PaddleX OCR HTTP protocol with validated, explicitly oriented geometry."""

import base64
import math
from pathlib import Path

from photo_organizer.capabilities.adapters.http import request
from photo_organizer.core.errors import CapabilityError


def recognize(config, path):
    response = request(
        config,
        {
            "file": base64.b64encode(Path(path).read_bytes()).decode(),
            "fileType": 1,
            # Derivatives have already applied EXIF orientation. Keep geometric
            # coordinates in the supplied image; line orientation remains enabled.
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
        },
    )
    if type(response.get("errorCode")) is not int or response["errorCode"] != 0:
        raise CapabilityError("ocr_failed", "PaddleOCR returned an unsuccessful result")
    result = response.get("result")
    pages = result.get("ocrResults") if isinstance(result, dict) else None
    if not isinstance(pages, list) or len(pages) != 1:
        raise CapabilityError("invalid_response", "Expected one PaddleOCR image result")
    item = pages[0].get("prunedResult") if isinstance(pages[0], dict) else None
    if not isinstance(item, dict):
        raise CapabilityError("invalid_response", "Missing PaddleOCR pruned result")
    texts, scores, boxes = (item.get(k) for k in ("rec_texts", "rec_scores", "rec_boxes"))
    if not all(isinstance(v, list) for v in (texts, scores, boxes)) or not (
        len(texts) == len(scores) == len(boxes)
    ):
        raise CapabilityError("invalid_response", "Inconsistent PaddleOCR text geometry")
    regions = []
    for text, score, box in zip(texts, scores, boxes):
        if (
            not isinstance(text, str)
            or type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= 1
            or not isinstance(box, list)
            or len(box) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
            or box[2] < box[0]
            or box[3] < box[1]
        ):
            raise CapabilityError("invalid_response", "Invalid PaddleOCR text region")
        regions.append({"text": text, "confidence": score, "box": box})
    text = "\n".join(texts)
    if len(text) > 100000:
        raise CapabilityError("invalid_response", "OCR text exceeds size limit")
    return {"text": text, "regions": regions, "coordinate_system": "input_pixels_xyxy"}
