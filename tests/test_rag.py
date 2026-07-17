
import sys
from pathlib import Path

# Ensure the project root is on sys.path so we can import app modules
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag import SimpleRetriever
from app.core.symbol_index import SymbolIndex

def test_simple_retriever_returns_empty_on_empty_index():
    # Create a SymbolIndex with no files
    idx = SymbolIndex('.')
    # Ensure internal structures are empty
    idx.files = {}
    idx.symbols = {}
    retriever = SimpleRetriever(idx)
    results = retriever.retrieve('nothing', limit=5)
    assert results == []

def test_simple_retriever_returns_something_when_matching():
    # We'll create a minimal symbol index with a dummy file
    idx = SymbolIndex('.')
    # Manually inject a file and symbol
    idx.files['dummy.py'] = 'def foo():\\n    pass'
    # Build symbol index manually (since we don't want to parse)
    idx.symbols['dummy.py'] = [{'type': 'function', 'name': 'foo', 'line': 1, 'end_line': 2}]
    retriever = SimpleRetriever(idx)
    results = retriever.retrieve('foo', limit=5)
    # Should find the function
    assert len(results) >= 1
    assert results[0]['name'] == 'foo'
    assert results[0]['file'] == 'dummy.py'

