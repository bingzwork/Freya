from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from PIL import Image, ImageOps


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def average_hash(image: Image.Image, size: int = 16) -> int:
    gray = ImageOps.grayscale(image).resize((size, size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    mean = sum(pixels) / max(1, len(pixels))
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= mean)
    return value


def average_hash_file(path: str | Path, size: int = 16) -> int:
    with Image.open(path) as image:
        return average_hash(image.convert("RGB"), size=size)


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def perceptual_similarity(left_hash: int, right_hash: int, bits: int = 256) -> float:
    return max(0.0, min(1.0, 1.0 - (hamming_distance(left_hash, right_hash) / float(bits))))


def safe_remote_image_bytes(url: str, *, timeout: float = 8.0, max_bytes: int = 1_500_000) -> bytes | None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    request = Request(str(url), headers={"User-Agent": "Freya/1.0 public-image-research"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                return None
            data = response.read(max_bytes + 1)
            return data if len(data) <= max_bytes else None
    except Exception:
        return None


def compare_candidate(local_path: str | Path, image_url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """Return honest local-vs-remote evidence; no data means no invented score."""
    local_sha = sha256_file(local_path)
    try:
        local_hash = average_hash_file(local_path)
    except Exception:
        local_hash = None
    payload = safe_remote_image_bytes(image_url, timeout=timeout)
    if not payload:
        return {"sha256": local_sha, "match_type": "unscored", "relevance": None}
    try:
        with Image.open(io.BytesIO(payload)) as remote:
            remote_sha = hashlib.sha256(payload).hexdigest()
            if remote_sha == local_sha:
                return {"sha256": local_sha, "candidate_sha256": remote_sha, "match_type": "exact", "relevance": "high"}
            if local_hash is None:
                return {"sha256": local_sha, "candidate_sha256": remote_sha, "match_type": "possible_source", "relevance": None}
            similarity = perceptual_similarity(local_hash, average_hash(remote.convert("RGB")))
            if similarity >= 0.92:
                qualitative = "high"
            elif similarity >= 0.78:
                qualitative = "medium"
            else:
                qualitative = "low"
            return {"sha256": local_sha, "candidate_sha256": remote_sha, "match_type": "visually_similar" if similarity >= 0.78 else "related", "relevance": qualitative, "similarity_score": round(similarity, 4)}
    except Exception:
        return {"sha256": local_sha, "match_type": "unscored", "relevance": None}


def deduplicate_candidates(records: Iterable[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        image_url = str(record.get("image_url") or record.get("thumbnail_url") or "").strip()
        source_url = str(record.get("source_page_url") or record.get("url") or "").strip()
        marker = str(record.get("candidate_sha256") or record.get("image_sha256") or image_url.split("?", 1)[0].lower() or source_url.split("?", 1)[0].lower())
        if not marker or marker in seen:
            continue
        seen.add(marker)
        record = dict(record)
        record.setdefault("provider", "free_image_research")
        record.setdefault("match_type", "related")
        record.setdefault("relevance", None)
        record["image_url"] = image_url
        record["thumbnail_url"] = str(record.get("thumbnail_url") or image_url).strip()
        record["url"] = source_url
        result.append(record)
        if len(result) >= max(1, min(int(limit), 20)):
            break
    return result
