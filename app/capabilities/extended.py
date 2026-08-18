"""Provider-based extensions for the ten audited capability areas.

The module deliberately contains small, injectable adapters rather than vendor
integrations.  Optional providers can be supplied by applications without
changing routing, and unavailable providers return deterministic errors.
"""
from __future__ import annotations

import csv
import json
import os
import platform
import shutil
import sqlite3
import re
import statistics
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, Sequence

from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata
from app.orchestrator.capabilities import BaseCapability


class CapabilityUnavailable(RuntimeError):
    """Raised when an optional provider is not configured or installed."""


class ProviderUnavailable:
    name = "unconfigured"
    def __getattr__(self, _name: str):
        def unavailable(**_kwargs):
            raise CapabilityUnavailable("No provider is configured for this operation")
        return unavailable


def _ok(**data: Any) -> Dict[str, Any]:
    return {"success": True, **data}


def _error(error: Any) -> Dict[str, Any]:
    return {"success": False, "error": str(error)}


class GuardedCapability(BaseCapability):
    """Base class that preserves an explicit approval boundary for mutations."""
    MUTATING_ACTIONS: frozenset[str] = frozenset()

    def _approved(self, inputs: Mapping[str, Any]) -> bool:
        # SafetyGate normally approves before capability dispatch.  The direct
        # boundary remains fail-closed for callers/tests that invoke a capability.
        return inputs.get("approved") is True or inputs.get("approval") in {True, "approved", "yes"}

    def _guard(self, action: str, inputs: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        if action in self.MUTATING_ACTIONS and not self._approved(inputs):
            return _error(f"Approval required for mutating action '{action}'")
        return None

    def _run(self, action: str, inputs: Dict[str, Any], fn):
        denied = self._guard(action, inputs)
        if denied:
            return denied
        try:
            return fn()
        except (CapabilityUnavailable, FileNotFoundError, OSError, ValueError, TypeError, sqlite3.Error) as exc:
            return _error(exc)


class DesktopProvider(Protocol):
    name: str
    def open(self, target: str) -> Any: ...
    def click(self, x: int, y: int, button: str = "left") -> Any: ...
    def type_text(self, text: str) -> Any: ...
    def hotkey(self, keys: Sequence[str]) -> Any: ...
    def screenshot(self, path: str) -> Any: ...


class LocalDesktopProvider:
    name = "local"
    def open(self, target: str):
        if platform.system() == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", target], check=True)
        else:
            subprocess.run(["xdg-open", target], check=True)
        return {"target": target}
    def click(self, x: int, y: int, button: str = "left"):
        raise CapabilityUnavailable("GUI automation provider is not installed; inject a DesktopProvider")
    def type_text(self, text: str):
        raise CapabilityUnavailable("GUI automation provider is not installed; inject a DesktopProvider")
    def hotkey(self, keys: Sequence[str]):
        raise CapabilityUnavailable("GUI automation provider is not installed; inject a DesktopProvider")
    def screenshot(self, path: str):
        raise CapabilityUnavailable("GUI screenshot provider is not installed; inject a DesktopProvider")


class ComputerCapability(GuardedCapability):
    MUTATING_ACTIONS = frozenset({"open", "click", "type_text", "hotkey"})
    def __init__(self, provider: Optional[DesktopProvider] = None):
        super().__init__(CapabilityMetadata(name="computer", description="Controlled desktop and computer actions", category=CapabilityCategory.TOOL, default_action="inspect", supported_actions=["inspect", "open", "click", "type_text", "hotkey", "screenshot"], tags=["computer", "desktop", "gui", "mouse", "keyboard", "screenshot"], safe_query=True))
        self.provider = provider or LocalDesktopProvider()
    def action_inspect(self, inputs):
        return _ok(platform=platform.system(), provider=getattr(self.provider, "name", "unknown"))
    def action_open(self, inputs):
        return self._run("open", inputs, lambda: _ok(result=self.provider.open(str(inputs["target"]))))
    def action_click(self, inputs):
        return self._run("click", inputs, lambda: _ok(result=self.provider.click(int(inputs["x"]), int(inputs["y"]), str(inputs.get("button", "left")))))
    def action_type_text(self, inputs):
        return self._run("type_text", inputs, lambda: _ok(result=self.provider.type_text(str(inputs["text"]))))
    def action_hotkey(self, inputs):
        return self._run("hotkey", inputs, lambda: _ok(result=self.provider.hotkey([str(k) for k in inputs["keys"]])))
    def action_screenshot(self, inputs):
        return self._run("screenshot", inputs, lambda: _ok(path=self.provider.screenshot(str(inputs["path"]))))


class FFmpegProvider:
    name = "ffmpeg"
    def __init__(self, binary: Optional[str] = None):
        self.binary = binary or shutil.which("ffmpeg")
    def _run(self, args: Sequence[str]):
        if not self.binary:
            raise CapabilityUnavailable("FFmpeg is unavailable; install it or inject a media provider")
        return subprocess.run([self.binary, *args], capture_output=True, text=True, check=True)
    def metadata(self, path: str):
        if not shutil.which("ffprobe"):
            raise CapabilityUnavailable("ffprobe is unavailable")
        result = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    def transform(self, args: Sequence[str], output: str):
        self._run([*args, "-y", output]); return output


class MediaCapability(GuardedCapability):
    MUTATING_ACTIONS = frozenset({"convert", "normalize", "trim", "split", "join", "extract_audio", "export", "cut", "concatenate", "crop", "resize", "add_audio", "remove_audio", "replace_audio", "burn_captions"})
    def __init__(self, name: str, description: str, actions: Sequence[str], provider: Optional[FFmpegProvider] = None, tags: Optional[Sequence[str]] = None):
        super().__init__(CapabilityMetadata(name=name, description=description, category=CapabilityCategory.TOOL, default_action="inspect", supported_actions=list(actions), tags=list(tags or []), safe_query=True))
        self.provider = provider or FFmpegProvider()
    def action_inspect(self, inputs):
        return self._run("inspect", inputs, lambda: _ok(metadata=self.provider.metadata(str(inputs["path"]))))
    def _transform(self, action: str, inputs: Mapping[str, Any], args: Sequence[str]):
        output = str(inputs.get("output") or inputs.get("path"))
        if not output: return _error("output is required")
        return self._run(action, inputs, lambda: _ok(output=self.provider.transform(args, output)))
    def action_convert(self, inputs): return self._transform("convert", inputs, ["-i", str(inputs["path"])])
    def action_export(self, inputs): return self.action_convert(inputs)
    def action_trim(self, inputs): return self._transform("trim", inputs, ["-ss", str(inputs["start"]), "-to", str(inputs["end"]), "-i", str(inputs["path"])])
    def action_cut(self, inputs): return self.action_trim(inputs)
    def action_extract_audio(self, inputs): return self._transform("extract_audio", inputs, ["-i", str(inputs["path"]), "-vn"])
    def action_remove_audio(self, inputs): return self._transform("remove_audio", inputs, ["-i", str(inputs["path"]), "-an"])
    def action_normalize(self, inputs): return self._transform("normalize", inputs, ["-i", str(inputs["path"]), "-af", "loudnorm"])
    def action_split(self, inputs): return self.action_trim(inputs)
    def action_join(self, inputs): return self._transform("join", inputs, ["-f", "concat", "-safe", "0", "-i", str(inputs["manifest"])])
    def action_concatenate(self, inputs): return self.action_join(inputs)
    def action_crop(self, inputs): return self._transform("crop", inputs, ["-i", str(inputs["path"]), "-vf", str(inputs["filter"])])
    def action_resize(self, inputs): return self._transform("resize", inputs, ["-i", str(inputs["path"]), "-vf", f"scale={inputs['width']}:{inputs['height']}"])
    def action_add_audio(self, inputs): return self._transform("add_audio", inputs, ["-i", str(inputs["video"]), "-i", str(inputs["audio"])])
    def action_replace_audio(self, inputs): return self.action_add_audio(inputs)
    def action_burn_captions(self, inputs): return self._transform("burn_captions", inputs, ["-i", str(inputs["path"]), "-vf", f"subtitles={inputs['captions']}"])


class ImageProvider(Protocol):
    name: str
    def edit(self, action: str, inputs: Mapping[str, Any]) -> Any: ...
    def generate(self, inputs: Mapping[str, Any]) -> Any: ...


class PillowImageProvider:
    name = "pillow"
    def edit(self, action: str, inputs: Mapping[str, Any]):
        try:
            from PIL import Image
        except ImportError as exc: raise CapabilityUnavailable(str(exc))
        image = Image.open(str(inputs["path"]))
        if action == "resize": image = image.resize((int(inputs["width"]), int(inputs["height"])))
        elif action == "crop": image = image.crop(tuple(int(v) for v in inputs["box"]))
        elif action == "rotate": image = image.rotate(float(inputs["degrees"]), expand=True)
        output = str(inputs.get("output") or inputs["path"])
        image.save(output, format=inputs.get("format"))
        return {"output": output, "size": image.size, "format": image.format}
    def generate(self, inputs):
        raise CapabilityUnavailable("No image-generation provider is configured")


class ImageCapability(GuardedCapability):
    MUTATING_ACTIONS = frozenset({"generate", "resize", "crop", "rotate", "compress", "convert", "remove_background", "composite", "overlay", "edit"})
    def __init__(self, provider: Optional[ImageProvider] = None):
        super().__init__(CapabilityMetadata(name="image", description="Provider-based image generation, editing, and metadata", category=CapabilityCategory.TOOL, default_action="metadata", supported_actions=["metadata", "generate", "resize", "crop", "rotate", "compress", "convert", "remove_background", "composite", "overlay", "edit"], tags=["image", "picture", "photo", "generate", "edit"], safe_query=True))
        self.provider = provider or PillowImageProvider()
    def action_metadata(self, inputs):
        try:
            from PIL import Image
            with Image.open(str(inputs["path"])) as image: return _ok(width=image.width, height=image.height, mode=image.mode, format=image.format)
        except Exception as exc: return _error(exc)
    def action_generate(self, inputs): return self._run("generate", inputs, lambda: _ok(result=self.provider.generate(inputs)))
    def action_edit(self, inputs): return self._run("edit", inputs, lambda: _ok(result=self.provider.edit(str(inputs.get("edit_action", "resize")), inputs)))
    def action_resize(self, inputs): return self.action_edit({**inputs, "edit_action": "resize"})
    def action_crop(self, inputs): return self.action_edit({**inputs, "edit_action": "crop"})
    def action_rotate(self, inputs): return self.action_edit({**inputs, "edit_action": "rotate"})
    def action_compress(self, inputs): return self.action_edit({**inputs, "edit_action": "compress"})
    def action_convert(self, inputs): return self.action_edit({**inputs, "edit_action": "convert"})
    def action_remove_background(self, inputs): return self._run("remove_background", inputs, lambda: _error("Background-removal provider is not configured"))
    def action_composite(self, inputs): return self._run("composite", inputs, lambda: _error("Compositing provider is not configured"))
    def action_overlay(self, inputs): return self._run("overlay", inputs, lambda: _error("Overlay provider is not configured"))


class ExternalProviderCapability(GuardedCapability):
    def __init__(self, name: str, description: str, actions: Sequence[str], mutating: Iterable[str], provider: Optional[Any] = None, tags: Optional[Sequence[str]] = None):
        super().__init__(CapabilityMetadata(name=name, description=description, category=CapabilityCategory.COMMUNICATION if name in {"email", "calendar", "contacts", "crm"} else CapabilityCategory.TOOL, default_action=actions[0], supported_actions=list(actions), tags=list(tags or []), safe_query=True))
        self.MUTATING_ACTIONS = frozenset(mutating)
        self.provider = provider or ProviderUnavailable()
    def _action(self, action: str, inputs: Mapping[str, Any]):
        return self._run(action, dict(inputs), lambda: _ok(result=getattr(self.provider, action)(**dict(inputs))))
    def __getattr__(self, name):
        if name.startswith("action_"):
            return lambda inputs: self._action(name[7:], inputs)
        raise AttributeError(name)


class DatabaseCapability(GuardedCapability):
    MUTATING_ACTIONS = frozenset({"execute", "insert", "update", "delete", "transaction"})
    def __init__(self, workspace: Optional[Path] = None, database_path: Optional[Path] = None):
        self.workspace = Path(workspace or Path.cwd()).expanduser().resolve()
        configured_path = Path(database_path or (self.workspace / "data" / "freya.db")).expanduser()
        self.database_path = (configured_path if configured_path.is_absolute() else self.workspace / configured_path).resolve()
        super().__init__(CapabilityMetadata(name="database", description="Safe parameterized database inspection and execution", category=CapabilityCategory.TOOL, default_action="inspect", supported_actions=["connect", "inspect", "list_tables", "columns", "query", "execute", "insert", "update", "delete", "transaction"], tags=["database", "sql", "sqlite", "query"], safe_query=True))
    def _resolve_path(self, inputs):
        raw_path = inputs.get("path") or self.database_path
        candidate = Path(str(raw_path)).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        candidate = candidate.resolve()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    @staticmethod
    def _params(inputs):
        params = inputs.get("params", [])
        if params is None:
            return ()
        if not isinstance(params, (list, tuple)):
            raise TypeError("Database params must be a list or tuple")
        return tuple(params)

    def _connect(self, inputs):
        return sqlite3.connect(str(self._resolve_path(inputs)), timeout=5.0)
    @staticmethod
    def _safe_identifier(value):
        name = str(value or "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Database identifier must contain only letters, numbers, and underscores")
        return "\"" + name + "\""

    def _natural_inputs(self, inputs):
        if inputs.get("sql") or not inputs.get("query"):
            return inputs
        text = str(inputs.get("query")).strip()
        lowered = text.lower()
        result = dict(inputs)
        table_match = re.search(r"(?:table|in)\s+(?:called\s+)?([A-Za-z_][A-Za-z0-9_]*)", text, re.IGNORECASE)
        table = table_match.group(1) if table_match else None
        if table and re.search(r"\b(create|make)\b.*\btable\b", lowered):
            fields_match = re.search(r"\bwith\s+(.+?)\s+fields?\b", text, re.IGNORECASE)
            names = re.split(r"\s*(?:,|\band\b)\s*", fields_match.group(1)) if fields_match else ["name", "email"]
            fields = [name.strip() for name in names if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.strip())]
            result["sql"] = "CREATE TABLE " + self._safe_identifier(table) + " (" + ", ".join(self._safe_identifier(name) + " TEXT" for name in fields) + ")"
            result["capability_action"] = "execute"
        elif table and re.search(r"\b(show|list|read)\b", lowered) and re.search(r"\b(records|rows|data)\b", lowered):
            result["sql"] = "SELECT * FROM " + self._safe_identifier(table)
            result["capability_action"] = "query"
        if "sql" not in result:
            insert_match = re.search(r"\b(?:add|insert)\s+([A-Za-z][A-Za-z0-9 _-]*?)\s+with\s+([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)\s+to\s+(?:table\s+)?([A-Za-z_][A-Za-z0-9_]*)", text, re.IGNORECASE)
            if insert_match:
                result["sql"] = "INSERT INTO " + self._safe_identifier(insert_match.group(3)) + " (name, email) VALUES (?, ?)"
                result["params"] = [insert_match.group(1).strip(), insert_match.group(2)]
                result["capability_action"] = "execute"
            else:
                update_match = re.search(r"\b(?:change|update)\s+(.+?)(?:'s)?\s+email\s+to\s+([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)\s+in\s+(?:table\s+)?([A-Za-z_][A-Za-z0-9_]*)", text, re.IGNORECASE)
                if update_match:
                    result["sql"] = "UPDATE " + self._safe_identifier(update_match.group(3)) + " SET email = ? WHERE name = ?"
                    result["params"] = [update_match.group(2), update_match.group(1).strip()]
                    result["capability_action"] = "execute"
                else:
                    delete_match = re.search(r"\bdelete\s+(.+?)\s+from\s+(?:table\s+)?([A-Za-z_][A-Za-z0-9_]*)", text, re.IGNORECASE)
                    if delete_match:
                        result["sql"] = "DELETE FROM " + self._safe_identifier(delete_match.group(2)) + " WHERE name = ?"
                        result["params"] = [delete_match.group(1).strip()]
                        result["capability_action"] = "execute"
        return result
    def action_inspect(self, inputs):
        parsed = self._natural_inputs(inputs)
        if parsed.get("capability_action") == "query":
            return self.action_query(parsed)
        if parsed.get("capability_action") == "execute":
            return self.action_execute(parsed)
        return self.action_list_tables(parsed)

    def action_list_tables(self, inputs):
        try:
            with self._connect(inputs) as db:
                rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            return _ok(path=str(self._resolve_path(inputs)), tables=[row[0] for row in rows])
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            return _error(exc)
    def action_connect(self, inputs):
        try:
            path = self._resolve_path(inputs)
            with self._connect(inputs): pass
            return _ok(connected=True, path=str(path))
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            return _error(exc)
    def action_columns(self, inputs):
        try:
            table = str(inputs.get("table") or "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                return _error("Database table name must be a simple SQL identifier")
            with self._connect(inputs) as db:
                rows = db.execute(f"PRAGMA table_info(\"{table}\")").fetchall()
            return _ok(table=table, columns=[{"name": row[1], "type": row[2], "nullable": not bool(row[3])} for row in rows])
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            return _error(exc)

    def action_query(self, inputs):
        try:
            sql = str(inputs["sql"]).strip()
            keyword = sql.split(None, 1)[0].upper().rstrip(";")
            if keyword in {"CREATE", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "REPLACE", "VACUUM", "ATTACH", "DETACH"}:
                return _error("Mutating SQL must use an approved database write action")
            inputs = {**inputs, "sql": sql}
            with self._connect(inputs) as db:
                cursor = db.execute(str(inputs["sql"]), self._params(inputs))
                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description or []]
            return _ok(columns=columns, rows=[dict(zip(columns, row)) for row in rows])
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            return _error(exc)

    def action_execute(self, inputs):
        denied = self._guard("execute", inputs)
        if denied:
            return denied
        try:
            with self._connect(inputs) as db:
                cur = db.execute(str(inputs["sql"]), self._params(inputs))
                return _ok(rowcount=cur.rowcount)
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            return _error(exc)
    def action_insert(self, inputs): return self.action_execute({**inputs, "sql": inputs["sql"]})
    def action_update(self, inputs): return self.action_execute({**inputs, "sql": inputs["sql"]})
    def action_delete(self, inputs): return self.action_execute({**inputs, "sql": inputs["sql"]})
    def action_transaction(self, inputs): return self.action_execute(inputs)


class VoiceCapability(ExternalProviderCapability):
    def __init__(self, provider=None):
        super().__init__("voice", "Provider-based speech transcription, synthesis, and voice interaction", ["transcribe", "speak"], ["speak"], provider, ["voice", "speech", "transcribe", "tts", "stt"])


class DataAnalysisCapability(GuardedCapability):
    def __init__(self):
        super().__init__(CapabilityMetadata(name="data_analysis", description="Reusable CSV, JSON, tabular analysis, summaries, and charts", category=CapabilityCategory.TOOL, default_action="analyze", supported_actions=["analyze", "summary", "filter", "group", "correlation", "chart"], tags=["data", "analysis", "csv", "json", "statistics", "chart"], safe_query=True))
    def _load(self, path):
        path = Path(path)
        if path.suffix.lower() == ".json": return json.loads(path.read_text())
        with path.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))
    def action_analyze(self, inputs):
        data = self._load(inputs["path"]); rows = data if isinstance(data, list) else [data]
        numeric = {}
        for key in rows[0].keys() if rows and isinstance(rows[0], dict) else []:
            vals = []
            for row in rows:
                try: vals.append(float(row[key]))
                except (KeyError, TypeError, ValueError): pass
            if vals: numeric[key] = {"count": len(vals), "mean": statistics.mean(vals), "min": min(vals), "max": max(vals)}
        return _ok(rows=len(rows), numeric=numeric, columns=list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [])
    def action_summary(self, inputs): return self.action_analyze(inputs)
    def action_filter(self, inputs):
        data = self._load(inputs["path"]); rows = data if isinstance(data, list) else []
        key, value = str(inputs["column"]), inputs.get("value")
        return _ok(rows=[row for row in rows if str(row.get(key)) == str(value)])
    def action_group(self, inputs):
        data = self._load(inputs["path"]); rows = data if isinstance(data, list) else []; key = str(inputs["column"]); groups = {}
        for row in rows: groups[str(row.get(key))] = groups.get(str(row.get(key)), 0) + 1
        return _ok(groups=groups)
    def action_correlation(self, inputs):
        data = self._load(inputs["path"]); rows = data if isinstance(data, list) else []; a, b = str(inputs["x"]), str(inputs["y"]); xs = [float(r[a]) for r in rows]; ys = [float(r[b]) for r in rows]
        return _ok(correlation=statistics.correlation(xs, ys))
    def action_chart(self, inputs): return _error("Chart rendering requires an injected visualization provider")


class IoTCapability(ExternalProviderCapability):
    def __init__(self, provider=None):
        super().__init__("iot", "Provider-neutral smart-home and IoT device state operations", ["discover", "list_devices", "get_state", "read_sensors", "set_state", "scene", "automation_status"], ["set_state", "scene"], provider, ["iot", "smart home", "device", "home assistant", "mqtt"])


def build_extended_capabilities(*, workspace: Optional[Path] = None, database_path: Optional[Path] = None, providers: Optional[Mapping[str, Any]] = None) -> list[BaseCapability]:
    providers = providers or {}
    return [
        ComputerCapability(providers.get("computer")),
        MediaCapability("audio", "Audio and podcast processing primitives", ["inspect", "convert", "normalize", "trim", "split", "join", "extract_audio"], providers.get("audio"), ["audio", "podcast", "transcription"]),
        MediaCapability("video", "Controlled video editing and transcoding primitives", ["inspect", "trim", "cut", "concatenate", "split", "crop", "resize", "extract_audio", "remove_audio", "replace_audio", "add_audio", "burn_captions", "export"], providers.get("video"), ["video", "editing", "caption", "transcode"]),
        ImageCapability(providers.get("image")),
        ExternalProviderCapability("email", "Provider-neutral email search, reading, drafting, and delivery", ["search", "read", "draft", "reply", "forward", "send", "archive", "label"], ["send", "archive", "label"], providers.get("email"), ["email", "mail", "message"]),
        ExternalProviderCapability("calendar", "Provider-neutral calendar and availability operations", ["list", "search", "availability", "create", "update", "delete", "respond"], ["create", "update", "delete", "respond"], providers.get("calendar"), ["calendar", "event", "schedule"]),
        ExternalProviderCapability("contacts", "Contacts and small CRM provider primitives", ["create", "search", "read", "update", "delete"], ["create", "update", "delete"], providers.get("contacts"), ["contacts", "crm", "people", "leads"]),
        DatabaseCapability(workspace=workspace, database_path=database_path),
        VoiceCapability(providers.get("voice")),
        DataAnalysisCapability(),
        IoTCapability(providers.get("iot")),
    ]


__all__ = ["CapabilityUnavailable", "ComputerCapability", "MediaCapability", "ImageCapability", "DatabaseCapability", "VoiceCapability", "DataAnalysisCapability", "IoTCapability", "ExternalProviderCapability", "build_extended_capabilities"]
