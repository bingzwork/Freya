"""Vision capability with a real local multimodal Ollama adapter."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata
from app.orchestrator.capabilities import BaseCapability


@dataclass
class VisionEvidence:
    text: str = ""
    confidence: Optional[float] = None
    regions: List[Dict[str, Any]] = field(default_factory=list)
    fields: Dict[str, Any] = field(default_factory=dict)
    observations: Dict[str, Any] = field(default_factory=dict)
    source: Dict[str, Any] = field(default_factory=dict)
    uncertain: bool = False
    provider: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "confidence": self.confidence, "regions": self.regions, "fields": self.fields, "observations": self.observations, "source": self.source, "uncertain": self.uncertain, "provider": self.provider, "error": self.error}


class VisionProvider(Protocol):
    name: str
    def ocr(self, image_path: Path) -> VisionEvidence: ...
    def analyze(self, image_path: Path, question: str) -> VisionEvidence: ...
    def extract_fields(self, image_path: Path, fields: Iterable[str]) -> VisionEvidence: ...


class OllamaVisionProvider:
    """Multimodal provider backed by an already-installed local Ollama model."""
    name = "ollama-multimodal"

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None, timeout: Optional[float] = None):
        self.base_url = (base_url or os.getenv("FREYA_OLLAMA_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.model = model or os.getenv("FREYA_VISION_MODEL") or os.getenv("OLLAMA_MODEL") or "qwen3.5:4b"
        self.timeout = float(timeout or os.getenv("FREYA_VISION_TIMEOUT", "180"))

    def _request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(self.base_url + endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-800:]
            raise RuntimeError(f"Ollama vision request failed ({exc.code}): {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Local Ollama vision provider is unavailable at {self.base_url}: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Ollama vision provider returned an invalid response")
        return data

    def _encode(self, path: Path) -> str:
        try:
            return base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise RuntimeError(f"Image could not be read for visual analysis: {exc}") from exc

    def _analyze_paths(self, paths: List[Path], question: str, structured: bool = False) -> VisionEvidence:
        if not paths:
            return VisionEvidence(provider=self.name, error="At least one image is required for visual analysis", uncertain=True)
        images = []
        for path in paths:
            if not path.is_file():
                return VisionEvidence(provider=self.name, error=f"Image file does not exist: {path}", uncertain=True)
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            if not mime.startswith("image/"):
                return VisionEvidence(provider=self.name, error=f"Unsupported visual MIME type: {mime}", uncertain=True)
            images.append(self._encode(path))
        prompt = question.strip() or "Describe the visible content, scene, objects, layout, and any readable text in these images. Ground every observation in the pixels."
        payload = {"model": self.model, "stream": False, "messages": [{"role": "user", "content": prompt, "images": images}], "options": {"temperature": 0.1}}
        if structured:
            payload["format"] = "json"
        try:
            data = self._request("/api/chat", payload)
            message = data.get("message") if isinstance(data.get("message"), dict) else {}
            text = str(message.get("content") or data.get("response") or "").strip()
            if not text:
                return VisionEvidence(provider=self.name, source={"model": self.model, "base_url": self.base_url, "paths": [str(p) for p in paths]}, error="Multimodal vision returned no content", uncertain=True)
            observations = {}
            if structured:
                candidate = text.strip()
                if candidate.startswith("```"):
                    candidate = candidate.strip("`")
                    if candidate.lower().startswith("json"):
                        candidate = candidate[4:].strip()
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    return VisionEvidence(text=text, confidence=0.0, provider=self.name, source={"model": self.model, "base_url": self.base_url, "paths": [str(p) for p in paths], "image_count": len(paths)}, error=f"Structured vision returned invalid JSON: {exc}", uncertain=True)
                if not isinstance(parsed, dict):
                    return VisionEvidence(text=text, confidence=0.0, provider=self.name, source={"model": self.model, "base_url": self.base_url, "paths": [str(p) for p in paths], "image_count": len(paths)}, error="Structured vision returned a non-object JSON value", uncertain=True)
                observations = parsed
                description = str(parsed.get("description") or "").strip()
                if description:
                    text = description
            return VisionEvidence(text=text, confidence=0.88 if not structured or observations else 0.0, observations=observations, provider=self.name, source={"model": self.model, "base_url": self.base_url, "paths": [str(p) for p in paths], "image_count": len(paths), "structured": structured})
        except Exception as exc:
            return VisionEvidence(provider=self.name, source={"model": self.model, "base_url": self.base_url, "paths": [str(p) for p in paths]}, error=str(exc), uncertain=True)

    def analyze(self, image_path: Path, question: str) -> VisionEvidence:
        return self._analyze_paths([image_path], question)

    def analyze_structured(self, image_path: Path, question: str) -> VisionEvidence:
        prompt = question.strip() or "Identify grounded visual clues that could support public-web discovery."
        prompt += "\nReturn JSON only with exactly these keys: description (string), visible_text (array of strings), objects (array of strings), scene (string), clothing (array of strings), logos (array of strings), landmarks (array of strings), context_clues (array of strings), search_terms (array of 3 to 5 concise strings). Use empty arrays or empty strings when not visible. Never infer identity or private facts."
        return self._analyze_paths([image_path], prompt, structured=True)

    def analyze_many(self, image_paths: Iterable[Path], question: str) -> VisionEvidence:
        return self._analyze_paths(list(image_paths), question)

    def ocr(self, image_path: Path) -> VisionEvidence:
        return self.analyze(image_path, "Read and transcribe all visible text in this image exactly. If there is no readable text, say that clearly. Do not infer or invent text.")

    def extract_fields(self, image_path: Path, fields: Iterable[str]) -> VisionEvidence:
        requested = [str(field).strip() for field in fields if str(field).strip()]
        prompt = "Extract these requested fields from the image. Return each field on its own line as `field: value`; use `not visible` when the field cannot be grounded in the image: " + ", ".join(requested)
        evidence = self.analyze(image_path, prompt)
        for field_name in requested:
            match = re.search(rf"{re.escape(field_name)}\s*[:#-]\s*([^\n]+)", evidence.text, flags=re.IGNORECASE)
            if match:
                evidence.fields[field_name] = match.group(1).strip()
        return evidence


class LocalTesseractProvider:
    name = "tesseract"

    def ocr(self, image_path: Path) -> VisionEvidence:
        executable = shutil.which("tesseract")
        if not executable:
            return VisionEvidence(provider=self.name, error="Local OCR is unavailable because the tesseract executable is not installed", uncertain=True)
        try:
            result = subprocess.run([executable, str(image_path), "stdout", "-l", "eng"], capture_output=True, text=True, timeout=60, check=False)
            if result.returncode != 0:
                return VisionEvidence(provider=self.name, error=result.stderr.strip() or "Tesseract OCR failed", uncertain=True)
            text = result.stdout.strip()
            return VisionEvidence(text=text, confidence=0.65 if text else 0.0, provider=self.name, source={"path": str(image_path)}, uncertain=not bool(text), error=None if text else "OCR detected no text")
        except Exception as exc:
            return VisionEvidence(provider=self.name, error=f"Local OCR failed: {exc}", uncertain=True)

    def analyze(self, image_path: Path, question: str) -> VisionEvidence:
        evidence = self.ocr(image_path)
        if evidence.error and not evidence.text:
            return evidence
        evidence.error = "The configured local OCR provider does not support general visual questions"
        evidence.uncertain = True
        return evidence

    def extract_fields(self, image_path: Path, fields: Iterable[str]) -> VisionEvidence:
        evidence = self.ocr(image_path)
        for field_name in fields:
            match = re.search(rf"{re.escape(str(field_name))}\s*[:#-]\s*([^\n]+)", evidence.text, flags=re.IGNORECASE)
            if match:
                evidence.fields[str(field_name)] = match.group(1).strip()
        return evidence


class VisionCapability(BaseCapability):
    def __init__(self, provider: Optional[VisionProvider] = None, file_allowlist=None):
        super().__init__(CapabilityMetadata(name="vision", version="1.1.0", description="Local multimodal image understanding, OCR, visual questions, screenshots, and structured visual evidence", category=CapabilityCategory.KNOWLEDGE, is_singleton=True, auto_discoverable=True, safe_query=True, default_action="analyze", supported_actions=["ocr", "analyze", "structured_analyze", "describe", "extract_fields"], tags=["vision", "multimodal", "ocr", "image", "screenshot", "visual", "diagram", "ui", "fields"]))
        if provider is not None:
            self._provider = provider
        elif os.getenv("FREYA_VISION_PROVIDER", "ollama").strip().lower() == "tesseract":
            self._provider = LocalTesseractProvider()
        else:
            self._provider = OllamaVisionProvider()
        self._file_allowlist = file_allowlist

    def set_provider(self, provider: VisionProvider) -> None:
        self._provider = provider

    def set_file_allowlist(self, file_allowlist) -> None:
        self._file_allowlist = file_allowlist

    def _resolve_images(self, inputs: Dict[str, Any]) -> tuple[List[Path], Optional[str]]:
        raw_paths = inputs.get("paths") or inputs.get("image_paths")
        if raw_paths is None:
            raw_paths = [inputs.get("path") or inputs.get("file_reference")]
        if isinstance(raw_paths, (str, Path)):
            raw_paths = [raw_paths]
        paths = [Path(str(value)).resolve() for value in raw_paths if value]
        if not paths:
            return [], "Image path is required"
        for path in paths:
            if not path.is_file():
                return [], f"Image file does not exist: {path}"
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
                return [], f"Unsupported image type: {path.suffix or 'unknown'}"
            if self._file_allowlist is not None:
                try:
                    decision = self._file_allowlist.validate_path(path, operation="read")
                    if decision is False:
                        return [], f"Image access denied by the file allowlist: {path.name}"
                except Exception:
                    pass
        return paths, None

    def _result(self, paths: List[Path], evidence: VisionEvidence) -> Dict[str, Any]:
        payload = evidence.to_dict()
        payload["success"] = not bool(evidence.error) and bool(evidence.text or evidence.observations)
        if evidence.observations:
            payload["search_terms"] = evidence.observations.get("search_terms", [])
        payload["source"] = {**payload.get("source", {}), "files": [str(path) for path in paths], "provider": evidence.provider}
        if evidence.error:
            payload["message"] = evidence.error
        return payload

    def action_ocr(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        paths, error = self._resolve_images(inputs)
        if error:
            return {"success": False, "error": error, "message": error}
        evidence = self._provider.ocr(paths[0])
        return self._result(paths, evidence)

    def action_analyze(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if inputs.get("structured"):
            return self.action_structured_analyze(inputs)
        paths, error = self._resolve_images(inputs)
        if error:
            return {"success": False, "error": error, "message": error}
        question = str(inputs.get("question") or inputs.get("prompt") or inputs.get("query") or "Describe the visible content and any readable text in the image.").strip()
        analyze_many = getattr(self._provider, "analyze_many", None)
        evidence = analyze_many(paths, question) if callable(analyze_many) else self._provider.analyze(paths[0], question)
        return self._result(paths, evidence)

    def action_structured_analyze(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        paths, error = self._resolve_images(inputs)
        if error:
            return {"success": False, "error": error, "message": error, "observations": {}}
        question = str(inputs.get("question") or inputs.get("prompt") or inputs.get("query") or "").strip()
        method = getattr(self._provider, "analyze_structured", None)
        if callable(method):
            evidence = method(paths[0], question)
        else:
            evidence = self._provider.analyze(paths[0], question)
        return self._result(paths, evidence)

    def action_describe(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.action_analyze({**inputs, "question": inputs.get("question") or "Describe the scene, visible objects, layout, and readable text grounded in this image."})

    def action_extract_fields(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        paths, error = self._resolve_images(inputs)
        fields = inputs.get("fields")
        if error:
            return {"success": False, "error": error, "message": error}
        if not isinstance(fields, (list, tuple)) or not fields:
            return {"success": False, "error": "fields must be a non-empty list", "message": "fields must be a non-empty list"}
        evidence = self._provider.extract_fields(paths[0], [str(field) for field in fields])
        return self._result(paths, evidence)


__all__ = ["VisionCapability", "VisionEvidence", "VisionProvider", "OllamaVisionProvider", "LocalTesseractProvider"]
