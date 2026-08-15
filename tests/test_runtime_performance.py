from pathlib import Path
import time

import pytest

from app.core.background_jobs import BackgroundJobService
from app.core.project_index import ProjectIndex
from app.core.performance import BoundedTTLCache
from app.intelligence.context_builder import ContextBuilder


def test_incremental_index_skips_changes_and_handles_updates(tmp_path: Path):
    source = tmp_path / "a.py"
    source.write_text("x = 1", encoding="utf-8")
    index = ProjectIndex(tmp_path)
    first = index.build()
    assert "a.py" in first
    second = index.update()
    assert second["unchanged"] == ["a.py"]
    source.write_text("x = 2", encoding="utf-8")
    changed = index.update()
    assert changed["modified"] == ["a.py"]
    source.unlink()
    deleted = index.update()
    assert deleted["deleted"] == ["a.py"]


def test_bounded_cache_evicts_and_exposes_stats():
    cache = BoundedTTLCache(max_size=2, ttl_seconds=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None
    assert cache.get("c") == 3
    assert cache.stats()["size"] == 2


def test_background_queue_is_bounded():
    service = BackgroundJobService(max_pending_jobs=1)
    service.add_job(lambda: None)
    with pytest.raises(RuntimeError, match="queue is full"):
        service.add_job(lambda: None)
    service.shutdown(wait=False)


def test_context_builder_reuses_cached_context():
    class Symbols:
        symbols = {"a.py": [{"type": "function", "name": "f"}]}
        def get_file(self, path): return "def f():\n    return 1"
        def get_symbol_source(self, path, symbol): return "def f():\n    return 1"
    class Graph:
        def related_files(self, path): return []
    builder = ContextBuilder(Symbols(), Graph())
    match = [{"file": "a.py", "type": "function", "name": "f", "line": 1}]
    first = builder.build(match)
    second = builder.build(match)
    assert first == second
    assert builder._cache.stats()["hits"] == 1


def test_unified_retrieval_cache_hit():
    from app.memory.unified_retrieval import UnifiedRetrieval, RetrievalResult

    class Retriever:
        source_name = "fake"
        def __init__(self): self.calls = 0
        def is_available(self): return True
        def retrieve(self, query):
            self.calls += 1
            return [RetrievalResult("answer", "fake", "1", 0.9)]
    retrieval = UnifiedRetrieval()
    fake = Retriever()
    retrieval.add_retriever(fake)
    assert retrieval.retrieve("same")
    assert retrieval.retrieve("same")
    assert fake.calls == 1
    assert retrieval.performance_stats()["cache_hits"] == 1
