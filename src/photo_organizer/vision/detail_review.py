"""Configured vision review of a bounded high-resolution image or crop."""

import base64
import tempfile
from pathlib import Path

from photo_organizer.capabilities.registry import vision
from photo_organizer.core.errors import CapabilityError
from photo_organizer.vision import evidence


def review(state, result_id, file_id, condition, long_edge=2560, crop=None):
    """Escalate detail for text-only hosts; cropped absence is never proof of whole-image absence."""
    if not isinstance(condition, str) or not 1 <= len(condition.strip()) <= 2000:
        raise ValueError("condition must be 1..2000 characters")
    original = evidence.read(state, result_id, condition, limit=1)
    picture = evidence.image(state, result_id, file_id, long_edge, crop)
    provider = vision(state)
    criterion = condition
    if crop is not None:
        criterion = (
            "Only a crop of the original is visible. Judge the criterion about the WHOLE original. "
            "If it needs context outside the crop (including absence, counts or relationships), return uncertain. "
            "Criterion: " + condition
        )
    with tempfile.TemporaryDirectory(prefix="photo-detail-") as tmp:
        path = Path(tmp) / "detail.jpg"
        path.write_bytes(base64.b64decode(picture["data"]))
        judgment, metrics = provider.judge(path, criterion)
    if vision(state).version != provider.version:
        raise CapabilityError(
            "version_conflict", "Vision configuration changed during detail review"
        )
    record = {
        "file_id": file_id,
        "hash": picture["hash"],
        "verdict": judgment["verdict"],
        "evidence": ("crop=" + str(crop) + "; " if crop is not None else "high-resolution review; ")
        + judgment["evidence"],
    }
    saved = evidence.submit(
        state,
        result_id,
        [record],
        {"kind": "provider", "model": provider.model, "version": provider.version},
        condition,
        original["condition_version"],
    )
    return {
        **saved,
        "judgment": record,
        "input": {k: v for k, v in picture.items() if k != "data"},
        "usage": metrics["usage"],
    }
