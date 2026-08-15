"""Vision and OCR capability with provider-independent contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata
from app.orchestrator.capabilities import BaseCapability


@dataclass
class VisionEvidence:
    """Provider-neutral visual evidence returned to callers."""

    text: str = ""
    confidence: Optional[float] = None
    regions: List[Dict[str, Any]] = field(default_factory=list)
    fields: Dict[str, Any] = field(default_factory=dict)
    source: Dict[str, Any] = field(default_factory=dict)
    uncertain: bool = False
    provider: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "regions": self.regions,
            "fields": self.fields,
            "source": self.source,
            "uncertain": self.uncertain,
            "provider": self.provider,
            "error": self.error,
        }


class VisionProvider(Protocol):
    """Stable adapter contract for local OCR or future multimodal providers."""

    name: str

    def ocr(self, image_path: Path) -> VisionEvidence:
        ...

    def analyze(self, image_path: Path, question: str) -> VisionEvidence:
        ...

    def extract_fields(self, image_path: Path, fields: Iterable[str]) -> VisionEvidence:
        ...


class LocalTesseractProvider:
    """Optional offline OCR provider; it never invents text when OCR is unavailable."""

    name = "tesseract"

    def ocr(self, image_path: Path) -> VisionEvidence:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as error:
            return VisionEvidence(provider=self.name, error=f"Local OCR provider unavailable: {error}")

        try:
            image = Image.open(image_path)
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            words: List[str] = []
            regions: List[Dict[str, Any]] = []
            confidences: List[float] = []
            for index, raw_text in enumerate(data.get("text", [])):
                text = str(raw_text).strip()
                try:
                    confidence = float(data.get("conf", ["-1"])[index])
                except (ValueError, TypeError, IndexError):
                    confidence = -1.0
                if not text or confidence < 0:
                    continue
                words.append(text)
                confidences.append(confidence / 100.0)
                regions.append({
                    "text": text,
                    "confidence": round(confidence / 100.0, 4),
                    "left": data.get("left", [0])[index],
                    "top": data.get("top", [0])[index],
                    "width": data.get("width", [0])[index],
                    "height": data.get("height", [0])[index],
                })
            text = " ".join(words).strip()
            confidence = sum(confidences) / len(confidences) if confidences else None
            uncertain = not text or confidence is None or confidence < 0.55
            return VisionEvidence(
                text=text if not uncertain else text,
                confidence=confidence,
                regions=regions,
                uncertain=uncertain,
                provider=self.name,
                error="OCR confidence is low or no text was detected" if uncertain else None,
            )
        except Exception as error:  # provider errors are surfaced, never fabricated
            return VisionEvidence(provider=self.name, error=f"OCR failed: {error}")

    def analyze(self, image_path: Path, question: str) -> VisionEvidence:
        evidence = self.ocr(image_path)
        if evidence.error and not evidence.text:
            return evidence
        evidence.error = "Local OCR provider does not support visual question answering"
        evidence.uncertain = True
        return evidence

    def extract_fields(self, image_path: Path, fields: Iterable[str]) -> VisionEvidence:
        evidence = self.ocr(image_path)
        if not evidence.text:
            return evidence
        extracted: Dict[str, Any] = {}
        for field_name in fields:
            label = re.escape(str(field_name).strip())
            match = re.search(rf"{label}\s*[:#-]\s*([^\n]+)", evidence.text, re.IGNORECASE)
            extracted[str(field_name)] = match.group(1).strip() if match else None
        evidence.fields = extracted
        return evidence


class VisionCapability(BaseCapability):
    """Registered visual understanding boundary backed by an injectable provider."""

    def __init__(self, provider: Optional[VisionProvider] = None, file_allowlist=None):
        super().__init__(CapabilityMetadata(
            name="vision",
            version="1.0.0",
            description="Image understanding, OCR, visual questions, screenshots, and structured visual evidence",
            category=CapabilityCategory.KNOWLEDGE,
            is_singleton=True,
            auto_discoverable=True,
            safe_query=True,
            default_action="ocr",
            supported_actions=["ocr", "analyze", "extract_fields"],
            tags=[
                "vision", "ocr", "image", "screenshot", "scanned", "receipt", "read",
                "extract text", "visual", "ui", "error", "fields", "table", "labels",
            ],
        ))
        self._provider: VisionProvider = provider or LocalTesseractProvider()
        self._file_allowlist = file_allowlist

    def set_provider(self, provider: VisionProvider) -> None:
        self._provider = provider

    def set_file_allowlist(self, file_allowlist) -> None:
        self._file_allowlist = file_allowlist

    def action_ocr(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        path, error = self._resolve_image(inputs)
        if error:
            return self._error(error)
        evidence = self._provider.ocr(path)
        return self._result(path, evidence)

    def action_analyze(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        path, error = self._resolve_image(inputs)
        if error:
            return self._error(error)
        question = str(inputs.get("question") or inputs.get("prompt") or "").strip()
        if not question:
            return self._error("question is required for visual analysis")
        evidence = self._provider.analyze(path, question)
        return self._result(path, evidence)

    def action_extract_fields(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        path, error = self._resolve_image(inputs)
        if error:
            return self._error(error)
        fields = inputs.get("fields")
        if not isinstance(fields, (list, tuple)) or not fields:
            return self._error("fields must be a non-empty list")
        evidence = self._provider.extract_fields(path, [str(field) for field in fields])
        return self._result(path, evidence)

    def _resolve_image(self, inputs: Dict[str, Any]) -> tuple[Optional[Path], Optional[str]]:
        reference = inputs.get("file_reference")
        value = inputs.get("image_path") or inputs.get("file_path") or inputs.get("path")
        if value is None and isinstance(reference, dict):
            value = reference.get("path") or reference.get("local_path") or reference.get("uri")
        if not isinstance(value, str) or not value.strip():
            return None, "image_path or a local file_reference is required"
        if value.startswith("file://"):
            from urllib.parse import unquote, urlparse
            value = unquote(urlparse(value).path)
        path = Path(value).expanduser()
        try:
            path = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            return None, f"Image file is unavailable: {error}"
        if not path.is_file():
            return None, "Image reference is not a regular file"
        if path.suffix.lower() == ".pdf":
            return None, "PDF visual processing belongs to the existing document capability"
        allowed_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
        if path.suffix.lower() not in allowed_extensions:
            return None, f"Unsupported image type: {path.suffix or 'unknown'}"
        if self._file_allowlist is not None:
            try:
                from app.core.file_allowlist import FileOperation, PathType
                decision = self._file_allowlist.validate_path(
                    path, FileOperation.READ, source="VisionCapability", path_type=PathType.FILE
                )
                if getattr(decision, "decision", None).value != "allowed":
                    return None, f"Image access denied: {decision.reason}"
            except (AttributeError, OSError, ValueError, TypeError) as error:
                return None, f"Image access denied: {error}"
        return path, None

    @staticmethod
    def _result(path: Path, evidence: VisionEvidence) -> Dict[str, Any]:
        result = evidence.to_dict()
        result["source"] = {"path": str(path), "filename": path.name, "mime_type": _mime_type(path)}
        success = not bool(evidence.error and not evidence.text and not evidence.fields)
        return {
            "success": success,
            "evidence": result,
            "text": evidence.text,
            "fields": evidence.fields,
            "confidence": evidence.confidence,
            "uncertain": evidence.uncertain,
            "message": evidence.error or ("Visual evidence extracted" if success else "Visual extraction failed"),
        }

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"success": False, "error": message, "message": message}


def _mime_type(path: Path) -> str:
    import mimetypes
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


__all__ = ["VisionCapability", "VisionEvidence", "VisionProvider", "LocalTesseractProvider"]
