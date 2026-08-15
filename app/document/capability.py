"""Canonical modular document/content editing capability."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.file_allowlist import FileOperation
from app.orchestrator.capabilities import BaseCapability, FileOutputCapability, _FileCapabilityBase
from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata
from app.document.handlers import SUPPORTED_EXTENSIONS, handler_for


class DocumentEditingCapability(_FileCapabilityBase):
    """Read, transform, validate, and version supported local documents."""

    ACTIONS = ["inspect", "edit", "rewrite", "format", "save", "export"]

    def __init__(self, file_allowlist=None, output_root=None, file_output=None):
        super().__init__(
            CapabilityMetadata(
                name="document_editing",
                version="1.0.0",
                description="Read, edit, rewrite, format, validate, save, and export local documents",
                category=CapabilityCategory.TOOL,
                is_singleton=True,
                auto_discoverable=True,
                safe_query=True,
                default_action="inspect",
                supported_actions=list(self.ACTIONS),
                tags=["document", "content", "edit", "rewrite", "format", "export", "docx", "pdf", "spreadsheet", "presentation"],
                provides=["edited_file_reference", "document_metadata"],
            ),
            file_allowlist=file_allowlist,
            output_root=output_root,
        )
        self._file_output = file_output or FileOutputCapability(
            file_allowlist=self._file_allowlist,
            output_root=self._output_root,
        )

    def _source(self, inputs: Dict[str, Any]) -> tuple[Optional[Path], Optional[Dict[str, Any]]]:
        value = inputs.get("file_path") or inputs.get("path") or self._path_from_reference(inputs.get("file_reference"))
        if not value: return None, self._error("Document input requires 'file_path', 'path', or 'file_reference'.")
        try: requested = self._coerce_path(value)
        except ValueError as error: return None, self._error(str(error))
        path, error = self._validate_access(requested, FileOperation.READ, "DocumentEditingCapability")
        if error: return None, self._error(error)
        if path is None or not path.exists() or not path.is_file(): return None, self._error(f"Document does not exist or is not a file: {requested}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS: return None, self._error(f"Unsupported document format: {path.suffix or '<none>'}")
        return path, None

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
        return digest.hexdigest()

    def _output_path(self, source: Path, inputs: Dict[str, Any], extension: str) -> Path:
        requested = inputs.get("output_path") or inputs.get("destination_path") or inputs.get("destination")
        if requested:
            target = self._coerce_path(requested, base=self._output_root)
            if target.exists() and target.is_dir(): target = target / f"{source.stem}.edited{extension}"
            elif not target.suffix: target = target.with_suffix(extension)
            return target
        suffix = extension or source.suffix.lower()
        return source.with_name(f"{source.stem}.edited{suffix}")

    def _save_bytes(self, source: Path, content: bytes, extension: str, inputs: Dict[str, Any], validation: Dict[str, Any]) -> Dict[str, Any]:
        target = self._output_path(source, inputs, extension)
        if target.resolve() == source.resolve():
            return self._error("Source file and output file must differ; source files are never silently overwritten.")
        result = self._file_output.action_write({
            "content": content,
            "destination_path": str(target),
            "overwrite": False,
            "extension": extension,
        })
        if not result.get("success"): return result
        result.update({"source_path": str(source), "source_sha256": self._digest(source), "validation": validation, "format": extension.lstrip(".")})
        self._publish_event("document.output.saved", {"source": str(source), "output": result.get("saved_path"), "format": extension})
        return result

    def action_inspect(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        source, error = self._source(inputs)
        if error: return error
        try:
            inspection = handler_for(source).inspect(source)
            return {"success": True, "file_reference": self._metadata(source), "inspection": inspection}
        except Exception as exc:
            return self._error(f"Unable to inspect document: {exc}")

    def _transform(self, inputs: Dict[str, Any], export: bool = False) -> Dict[str, Any]:
        source, error = self._source(inputs)
        if error: return error
        original_digest = self._digest(source)
        try:
            handler = handler_for(source)
            extension = str(inputs.get("target_extension") or Path(inputs.get("output_path", "")).suffix or source.suffix).lower()
            if not extension.startswith("."): extension = "." + extension
            content = handler.export(source, extension, inputs) if export else handler.edit(source, inputs)
            target_handler = handler_for(Path(f"output{extension}"))
            validation = target_handler.validate(content, extension)
        except Exception as exc:
            return self._error(f"Unable to transform document: {exc}")
        if self._digest(source) != original_digest:
            return self._error("Source document changed during processing; refusing to save output.")
        return self._save_bytes(source, content, extension, inputs, validation)

    def action_edit(self, inputs: Dict[str, Any]) -> Dict[str, Any]: return self._transform(inputs)
    def action_rewrite(self, inputs: Dict[str, Any]) -> Dict[str, Any]: return self._transform(inputs)
    def action_format(self, inputs: Dict[str, Any]) -> Dict[str, Any]: return self._transform(inputs)
    def action_export(self, inputs: Dict[str, Any]) -> Dict[str, Any]: return self._transform(inputs, export=True)
    def action_save(self, inputs: Dict[str, Any]) -> Dict[str, Any]: return self._transform(inputs)


__all__ = ["DocumentEditingCapability"]
