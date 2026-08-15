import json
import sqlite3
from pathlib import Path

from app.capabilities.extended import (
    DatabaseCapability,
    DataAnalysisCapability,
    ImageCapability,
    IoTCapability,
    build_extended_capabilities,
)


def test_all_audited_capabilities_are_registered_by_factory():
    names = {cap.name for cap in build_extended_capabilities()}
    assert names == {
        "computer", "audio", "video", "image", "email", "calendar",
        "contacts", "database", "voice", "data_analysis", "iot",
    }


def test_database_uses_parameterized_read_query(tmp_path: Path):
    db_path = tmp_path / "data.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("create table sales (name text, amount real)")
        db.execute("insert into sales values (?, ?)", ("A", 10.0))
    result = DatabaseCapability().action_query({"path": str(db_path), "sql": "select * from sales where name = ?", "params": ["A"]})
    assert result["success"] is True
    assert result["rows"] == [{"name": "A", "amount": 10.0}]


def test_database_mutation_requires_approval(tmp_path: Path):
    result = DatabaseCapability().action_execute({"path": str(tmp_path / "x.sqlite"), "sql": "create table x (id integer)"})
    assert result == {"success": False, "error": "Approval required for mutating action 'execute'"}


def test_data_analysis_is_deterministic_for_csv(tmp_path: Path):
    path = tmp_path / "sales.csv"
    path.write_text("region,amount\nwest,10\neast,30\n", encoding="utf-8")
    result = DataAnalysisCapability().action_analyze({"path": str(path)})
    assert result["success"] is True
    assert result["rows"] == 2
    assert result["numeric"]["amount"]["mean"] == 20.0


def test_image_metadata_and_unavailable_generation(tmp_path: Path):
    from PIL import Image
    path = tmp_path / "image.png"
    Image.new("RGB", (4, 3), "white").save(path)
    metadata = ImageCapability().action_metadata({"path": str(path)})
    assert metadata["success"] is True
    assert (metadata["width"], metadata["height"]) == (4, 3)
    generated = ImageCapability().action_generate({"prompt": "test", "approved": True})
    assert generated["success"] is False
    assert "provider" in generated["error"].lower()


def test_iot_mutation_is_fail_closed_without_approval():
    result = IoTCapability().action_set_state({"device_id": "lamp", "state": "on"})
    assert result["success"] is False
    assert "Approval required" in result["error"]
