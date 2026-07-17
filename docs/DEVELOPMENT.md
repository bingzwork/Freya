# Development

Freya requires Python 3.11 or newer and an Ollama server with the configured
model available locally.

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Validate changes

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q app
```

The custom pytest options avoid Windows temporary-directory permissions in
restricted environments.

## Agent safety model

`FreyaAgent.run()` plans and executes at most eight steps. By default it can
only list and read files. Writing files, applying replacements, and terminal
commands require `allow_mutations=True` when calling the API. File operations
remain confined to the configured workspace, and replacements must identify
their original text exactly once.

## Code context

The context builder extracts the matching Python class or function rather than
the entire source file. It also follows direct imports that resolve inside the
workspace and includes a compact symbol from each dependency. This keeps model
requests focused without depending on an external vector database.

## Enhanced Retrieval (Semantic + Lexical)

`EnhancedRetriever` combines two search strategies:
- **Lexical Search** (`LexicalSearch`): Ranks source using task words, filenames, symbol names, source text, and docstrings. Dependency-free and runs locally.
- **Semantic Search** (`SemanticSearch`): Uses sentence-transformers/all-MiniLM-L6-v2 to encode symbols and compute cosine similarity for conceptual matching.

Results are combined with weighted scoring (60% lexical, 40% semantic) and deduplicated.

Caching: Embeddings are cached to `.semantic_cache/` for performance.

## Patch workflow

Use `agent.propose_patch(task)` to obtain a structured preview. It supports
only creating a new file or replacing an exact, unique text fragment. Call
`agent.apply_patch(proposal, allow_mutations=True)` only after reviewing the
proposal. `agent.verify()` runs the project's pytest suite without exposing an
unrestricted shell to the language model.

For an approved change that must pass tests, use
`agent.apply_patch_and_verify(proposal, allow_mutations=True)`. Freya restores
the original contents of every touched file if verification fails.

`agent.repair(task, allow_mutations=True)` uses the same transaction mechanism
for a bounded retry loop. Each failed attempt is rolled back before the next
proposal receives the concise verification output.

## Persistent memory

`ProjectMemory` stores recent tasks, verification results, and explicit design
decisions in `data/memory/freya_memory.json`. The store is local, bounded to
200 entries, and writes atomically. Recent entries are included in `run()`
prompts. Do not put credentials or sensitive user data into memory entries.

## Local retrieval

`LexicalSearch` ranks source using task words, filenames, symbol names, source
text, and docstrings. It is dependency-free and runs locally. It complements
exact `FileLocator` matches; it is not an embedding-based semantic search.

`SemanticSearch` provides conceptual matching via embeddings. Requires
sentence-transformers to be installed.
