from pathlib import Path
import json
import pytest
from app.capabilities.extended import DatabaseCapability
from main import FreyaApp

def make_db(tmp_path):
    return DatabaseCapability(workspace=tmp_path)

def test_sqlite_creation_and_persistence(tmp_path):
    db=make_db(tmp_path)
    connected=db.execute("connect",{})
    assert connected["success"] is True
    assert Path(connected["path"]).exists()
    assert db.execute("execute", {"sql":"CREATE TABLE contacts (name TEXT, email TEXT)","approved":True})["success"]
    assert db.execute("insert", {"sql":"INSERT INTO contacts (name,email) VALUES (?,?)","params":["Alice","alice@example.com"],"approved":True})["success"]
    second=make_db(tmp_path)
    selected=second.execute("query", {"sql":"SELECT name,email FROM contacts","params":[]})
    assert selected["rows"] == [{"name":"Alice","email":"alice@example.com"}]
    assert second.execute("update", {"sql":"UPDATE contacts SET email=? WHERE name=?","params":["alice2@example.com","Alice"],"approved":True})["success"]
    assert second.execute("delete", {"sql":"DELETE FROM contacts WHERE name=?","params":["Alice"],"approved":True})["success"]
    assert second.execute("query", {"sql":"SELECT * FROM contacts"})["rows"] == []

def test_parameterization_schema_and_errors(tmp_path):
    db=make_db(tmp_path)
    db.execute("execute", {"sql":"CREATE TABLE contacts (name TEXT, email TEXT)","approved":True})
    db.execute("insert", {"sql":"INSERT INTO contacts VALUES (?,?)","params":["A; DROP TABLE contacts; --","a@example.com"],"approved":True})
    assert db.execute("columns", {"table":"contacts"})["columns"][0]["name"] == "name"
    assert db.execute("query", {"sql":"SELECT name FROM contacts WHERE email=?","params":["a@example.com"]})["rows"][0]["name"].startswith("A;")
    assert db.execute("query", {"sql":"SELEC invalid"})["success"] is False
    assert db.execute("query", {"sql":"SELECT * FROM missing_table"})["success"] is False
    assert db.execute("query", {"sql":"DROP TABLE contacts"})["error"].startswith("Mutating SQL")
    assert db.execute("columns", {"table":"contacts; DROP TABLE contacts"})["success"] is False

def test_mutations_remain_approval_gated(tmp_path):
    db=make_db(tmp_path)
    denied=db.execute("execute", {"sql":"CREATE TABLE contacts (name TEXT)","approved":False})
    assert denied["success"] is False
    assert "Approval required" in denied["error"]

def test_natural_language_database_actions(tmp_path):
    db=make_db(tmp_path)
    assert db.execute("inspect", {"query":"Create a database table called test_contacts with name and email fields.","approved":True})["success"]
    assert db.execute("inspect", {"query":"Add Alice with alice@example.com to test_contacts.","approved":True})["success"]
    selected=db.execute("inspect", {"query":"Show me all records in test_contacts."})
    assert selected["rows"] == [{"name":"Alice","email":"alice@example.com"}]
    assert db.execute("inspect", {"query":"Change Alice email to alice2@example.com in test_contacts.","approved":True})["success"]
    assert db.execute("inspect", {"query":"Delete Alice from test_contacts."})["error"].startswith("Approval required")
    assert db.execute("inspect", {"query":"Delete Alice from test_contacts.","approved":True})["success"]

def test_production_database_route_uses_real_capability(tmp_path):
    app=FreyaApp(tmp_path)
    app.start()
    try:
        capability=app.system.orchestrator.capability_registry.get_capability("database")
        router=app.system.facade._control._router
        assert capability.execute("execute", {"sql":"CREATE TABLE test_contacts (name TEXT, email TEXT)", "approved": True})["success"]
        route=router.route("Show me all records in test_contacts.")
        assert capability is not None
        assert capability.database_path == (tmp_path / "data" / "freya.db").resolve()
        assert route.capability_name == "database"
        result=router._capability_router.execute_named("database", query="Show me all records in test_contacts.")
        assert result.success is True
        assert result.capability_name == "database"
    finally:
        app.shutdown()
