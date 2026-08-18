from pathlib import Path
from PIL import Image

from app.vision.capability import VisionCapability, VisionEvidence


class FakeVisionProvider:
    name = "fake-vision"

    def analyze_structured(self, image_path: Path, question: str):
        return VisionEvidence(
            text="A red bicycle is visible.",
            confidence=0.9,
            observations={
                "description": "A red bicycle is visible.",
                "visible_text": [],
                "objects": ["bicycle"],
                "scene": "outdoor street",
                "clothing": [],
                "logos": [],
                "landmarks": [],
                "context_clues": ["urban street"],
                "search_terms": ["red bicycle urban street", "bicycle model"]
            },
            provider=self.name,
        )

    def analyze(self, image_path: Path, question: str):
        return VisionEvidence(text="free-text", confidence=0.8, provider=self.name)

    def ocr(self, image_path: Path):
        return VisionEvidence(text="", provider=self.name)

    def extract_fields(self, image_path: Path, fields):
        return VisionEvidence(text="", provider=self.name)


def test_structured_action_returns_observations_and_terms(tmp_path):
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (8, 8), "red").save(image_path)
    capability = VisionCapability(provider=FakeVisionProvider())
    result = capability.action_structured_analyze({"path": str(image_path)})
    assert result["success"] is True
    assert result["observations"]["objects"] == ["bicycle"]
    assert result["search_terms"] == ["red bicycle urban street", "bicycle model"]


def test_analyze_keeps_free_text_action_compatible(tmp_path):
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (8, 8), "red").save(image_path)
    capability = VisionCapability(provider=FakeVisionProvider())
    result = capability.action_analyze({"path": str(image_path)})
    assert result["success"] is True
    assert result["text"] == "free-text"
