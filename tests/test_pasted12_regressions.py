import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(r"C:\AI Projects\Freya")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_no_bing_key_required(monkeypatch):
    monkeypatch.delenv("FREYA_IMAGE_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("BING_IMAGE_SEARCH_KEY", raising=False)
    from app.research.capability import ResearchCapability
    capability = ResearchCapability()
    assert capability.image_research.__class__.__name__ == "FreeImageResearchChain"
    assert "bing" not in repr(capability.image_research).lower()


def test_name_photo_uses_text_search_not_reverse_image():
    from ui_server import _image_search_query, _is_image_search_request, _is_reverse_image_request
    request = "find photos of goddess freya"
    assert _is_image_search_request(request)
    assert not _is_reverse_image_request(request)
    assert _image_search_query(request).lower() == "goddess freya"


def test_attached_reverse_request_uses_reverse_intent():
    from ui_server import _is_image_search_request, _is_reverse_image_request
    request = "find similar images to this"
    assert _is_reverse_image_request(request)
    assert not _is_image_search_request(request)


def test_reverse_image_capability_delegates_to_chain(tmp_path):
    from app.research.capability import ResearchCapability
    image_path = tmp_path / "uploaded.png"
    Image.new("RGB", (24, 24), (120, 80, 40)).save(image_path)

    class Chain:
        def search(self, path, *, limit=10):
            assert Path(path).resolve() == image_path.resolve()
            return {"success": True, "provider": "free_image_research", "image_results": [{"title": "candidate", "image_url": "https://images.example/candidate.jpg"}]}

    capability = ResearchCapability()
    capability.osint.reverse_image_provider = Chain()
    result = capability.action_reverse_image_search({"image_path": str(image_path), "limit": 5})
    assert result["success"] is True
    assert result["matches"][0]["image_url"].startswith("https://")


def test_vision_fallback_runs_when_browser_providers_unavailable(monkeypatch, tmp_path):
    from app.free_image_research_providers import FreeImageResearchChain
    image_path = tmp_path / "uploaded.png"
    Image.new("RGB", (24, 24), (20, 60, 140)).save(image_path)

    class Vision:
        def execute(self, action, inputs):
            assert action == "structured_analyze"
            return {"success": True, "data": {"search_terms": ["blue shrine landscape"]}}

    class Search:
        def search(self, query, max_results=8):
            return {"results": [{"title": "Blue shrine photo", "url": "https://example.org/page", "image_url": "https://example.org/photo.jpg"}]}

    monkeypatch.setattr("app.free_image_research_providers.extract_public_page_images", lambda url, **kwargs: [])
    chain = FreeImageResearchChain(Search(), browser=None, vision=Vision())
    outcome = chain.search(str(image_path), limit=5)
    assert outcome["success"] is True
    assert outcome["provider"] == "vision_web_fallback"
    assert outcome["image_results"][0]["image_url"].startswith("https://")


def test_local_matching_exact(monkeypatch, tmp_path):
    import app.free_image_matching as matching
    image = Image.new("RGB", (32, 32), (200, 100, 20))
    local_path = tmp_path / "local.png"
    payload = _png_bytes(image)
    local_path.write_bytes(payload)
    monkeypatch.setattr(matching, "safe_remote_image_bytes", lambda url, timeout=8.0: payload)
    result = matching.compare_candidate(local_path, "https://example.org/exact.png")
    assert result["match_type"] == "exact"
    assert result["relevance"] == "high"


def test_local_matching_perceptual(monkeypatch, tmp_path):
    import app.free_image_matching as matching
    image = Image.new("RGB", (32, 32), (200, 100, 20))
    local_path = tmp_path / "local.png"
    local_path.write_bytes(_png_bytes(image))
    resized = image.resize((64, 64))
    monkeypatch.setattr(matching, "safe_remote_image_bytes", lambda url, timeout=8.0: _png_bytes(resized))
    result = matching.compare_candidate(local_path, "https://example.org/resized.png")
    assert result["match_type"] in {"visually_similar", "related"}


def test_deduplication():
    from app.free_image_matching import deduplicate_candidates
    records = [
        {"title": "First", "image_url": "https://cdn.example/a.jpg", "url": "https://example.org/a"},
        {"title": "Duplicate", "image_url": "https://cdn.example/a.jpg?size=large", "url": "https://example.org/b"},
        {"title": "Second", "image_url": "https://cdn.example/b.jpg", "url": "https://example.org/c"},
    ]
    result = deduplicate_candidates(records, limit=10)
    assert len(result) == 2
    assert result[0]["title"] == "First"
