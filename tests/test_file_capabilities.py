from pathlib import Path
import os

import pytest

from app.capabilities.registration_bridge import CapabilityRegistrationBridge
from app.capabilities.router import CapabilityRouter
from app.core.file_allowlist import (
    AccessRule,
    FileAllowlist,
    FileAllowlistConfig,
    FileOperation,
)
from app.core.tool_manager import ToolManager
from app.orchestrator.capabilities import FileInputCapability, FileOutputCapability, create_all_capabilities
from app.orchestrator.capability_registry import CapabilityRegistry, reset_capability_registry


def _file_allowlist(root: Path, extensions=None) -> FileAllowlist:
    config = FileAllowlistConfig(
        allow_current_directory=False,
        allow_temp_directory=False,
        allow_home_directory=False,
    )
    config.allowed_extensions.update(extensions or {".txt", ".pdf"})
    allowlist = FileAllowlist(config)
    allowlist.add_rule(
        AccessRule(
            pattern=f"{root.resolve()}/**",
            operations={
                FileOperation.READ,
                FileOperation.WRITE,
                FileOperation.CREATE,
            },
            description="Focused file capability test workspace",
        )
    )
    return allowlist


def test_file_input_accepts_valid_file_and_returns_normalized_reference(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Freya file input", encoding="utf-8")
    capability = FileInputCapability(file_allowlist=_file_allowlist(tmp_path))

    result = capability.action_intake({"file_path": str(source)})

    assert result["success"] is True
    reference = result["file_reference"]
    assert reference["path"] == str(source.resolve())
    assert reference["uri"] == source.resolve().as_uri()
    assert reference["filename"] == "notes.txt"
    assert reference["extension"] == ".txt"
    assert reference["file_type"] == "text"
    assert reference["size_bytes"] == len("Freya file input")


def test_file_reference_uri_normalization_preserves_windows_drive_and_spaces():
    reference = "file:///C:/Users/Test User/report%20draft.pdf"
    normalized = FileInputCapability._path_from_reference(reference)
    expected = "C:/Users/Test User/report draft.pdf"
    if os.name == "nt":
        expected = expected.replace("/", "\\")
    assert normalized == expected



def test_file_reference_uri_normalization_preserves_posix_file_uri():
    reference = "file:///tmp/report%20draft.pdf"
    normalized = FileInputCapability._path_from_reference(reference)
    expected = "/tmp/report draft.pdf"
    if os.name == "nt":
        expected = expected.replace("/", "\\")
    assert normalized == expected



def test_file_reference_normalization_leaves_ordinary_path_unchanged():
    ordinary_path = os.path.join("workspace", "report draft.pdf")
    assert FileInputCapability._path_from_reference(ordinary_path) == ordinary_path

def test_file_input_rejects_missing_file(tmp_path):
    capability = FileInputCapability(file_allowlist=_file_allowlist(tmp_path))

    result = capability.action_intake({"file_path": str(tmp_path / "missing.txt")})

    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_file_input_detects_pdf_metadata_from_future_ui_reference(tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.7\nminimal")
    capability = FileInputCapability(file_allowlist=_file_allowlist(tmp_path))

    result = capability.action_intake(
        {"file_reference": {"id": "ui-file-1", "uri": source.resolve().as_uri()}}
    )

    assert result["success"] is True
    reference = result["file_reference"]
    assert reference["filename"] == "report.pdf"
    assert reference["extension"] == ".pdf"
    assert reference["mime_type"] == "application/pdf"
    assert reference["file_type"] == "pdf"
    assert reference["source_reference_id"] == "ui-file-1"


def test_file_output_writes_artifact_and_creates_destination_directory(tmp_path):
    capability = FileOutputCapability(
        file_allowlist=_file_allowlist(tmp_path),
        output_root=tmp_path,
    )
    destination = tmp_path / "exports" / "summary.txt"

    result = capability.action_write(
        {"content": "Generated summary", "destination_path": str(destination)}
    )

    assert result["success"] is True
    assert Path(result["saved_path"]) == destination.resolve()
    assert destination.read_text(encoding="utf-8") == "Generated summary"
    assert result["file_reference"]["size_bytes"] == len("Generated summary")
    assert result["overwritten"] is False


def test_file_output_generates_a_filename_when_none_is_supplied(tmp_path):
    capability = FileOutputCapability(
        file_allowlist=_file_allowlist(tmp_path),
        output_root=tmp_path,
    )

    result = capability.action_write({"content": "Generated artifact"})

    assert result["success"] is True
    saved_path = Path(result["saved_path"])
    assert saved_path.parent == (tmp_path / "outputs").resolve()
    assert saved_path.name.startswith("artifact-")
    assert saved_path.suffix == ".txt"
    assert saved_path.read_text(encoding="utf-8") == "Generated artifact"


def test_file_output_refuses_overwrite_without_explicit_permission(tmp_path):
    destination = tmp_path / "exports" / "existing.txt"
    destination.parent.mkdir()
    destination.write_text("Original", encoding="utf-8")
    capability = FileOutputCapability(
        file_allowlist=_file_allowlist(tmp_path),
        output_root=tmp_path,
    )

    result = capability.action_write(
        {"content": "Replacement", "destination_path": str(destination)}
    )

    assert result["success"] is False
    assert "Refusing to overwrite" in result["error"]
    assert destination.read_text(encoding="utf-8") == "Original"


def test_file_output_overwrites_only_when_explicitly_requested(tmp_path):
    destination = tmp_path / "existing.txt"
    destination.write_text("Original", encoding="utf-8")
    capability = FileOutputCapability(
        file_allowlist=_file_allowlist(tmp_path),
        output_root=tmp_path,
    )

    result = capability.action_write(
        {
            "content": "Replacement",
            "destination_path": str(destination),
            "overwrite": True,
        }
    )

    assert result["success"] is True
    assert result["overwritten"] is True
    assert destination.read_text(encoding="utf-8") == "Replacement"


def test_file_output_copies_an_existing_artifact(tmp_path):
    source = tmp_path / "generated.pdf"
    source.write_bytes(b"%PDF-1.7\nartifact")
    destination = tmp_path / "exports" / "published.pdf"
    capability = FileOutputCapability(
        file_allowlist=_file_allowlist(tmp_path),
        output_root=tmp_path,
    )

    result = capability.action_write(
        {"artifact_path": str(source), "destination_path": str(destination)}
    )

    assert result["success"] is True
    assert destination.read_bytes() == source.read_bytes()
    assert result["file_reference"]["file_type"] == "pdf"


def test_default_file_policy_allows_passive_artifact_extensions_but_blocks_binaries():
    config = FileAllowlistConfig()

    assert ".pdf" in config.allowed_extensions
    assert ".png" in config.allowed_extensions
    assert ".mp3" in config.allowed_extensions
    assert ".xlsx" in config.allowed_extensions
    assert ".exe" in config.blocked_extensions


def test_file_capabilities_register_and_route_through_canonical_bridge(tmp_path):
    reset_capability_registry()
    try:
        allowlist = _file_allowlist(tmp_path)
        source = tmp_path / "input.txt"
        source.write_text("Input artifact", encoding="utf-8")
        registry = CapabilityRegistry()
        registry.register(FileInputCapability(file_allowlist=allowlist))
        registry.register(FileOutputCapability(file_allowlist=allowlist, output_root=tmp_path))
        registry.start()

        tool_manager = ToolManager(tmp_path, file_allowlist=allowlist)
        router = CapabilityRouter()
        bridge = CapabilityRegistrationBridge(
            registry=registry,
            router=router,
            tool_manager=tool_manager,
        )
        bridge.sync()

        input_result = router.execute_named("file_input", file_path=str(source))
        output_result = router.execute_named(
            "file_output",
            content="Routed output",
            destination_path=str(tmp_path / "routed" / "output.txt"),
        )

        assert {"file_input", "file_output"}.issubset(set(router.get_capabilities()))
        assert "capability::file_input" in tool_manager.tools
        assert "capability::file_output" in tool_manager.tools
        assert input_result.success is True
        assert input_result.data["file_reference"]["filename"] == "input.txt"
        assert output_result.success is True
        assert Path(output_result.data["saved_path"]).read_text(encoding="utf-8") == "Routed output"
    finally:
        reset_capability_registry()


def test_factory_includes_file_capabilities():
    capabilities = create_all_capabilities()

    assert any(isinstance(capability, FileInputCapability) for capability in capabilities)
    assert any(isinstance(capability, FileOutputCapability) for capability in capabilities)
