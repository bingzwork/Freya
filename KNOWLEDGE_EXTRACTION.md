# Knowledge Extraction

## Status
✅ **IMPLEMENTED**

## Overview
A complete, structured pipeline for converting raw information from various sources into reusable knowledge objects that can be stored, validated, retrieved, and used by Planning, Reasoning, Memory, Decision Making, Autonomous Learning, and Software Engineering capabilities.

## Purpose
Transform information from various sources into a consistently formatted, searchable knowledge base.

## Implementation Summary
- **Implementation:** Complete (core pipeline + LLM extractor + Documentation extractor)
- **Priority:** ⭐⭐⭐⭐⭐ Critical
- **Location:** `app/knowledge_extraction/`
- **Tests:** `tests/test_knowledge_extraction.py` (30 tests passing)

## High-Level Workflow (Implemented)
1. **Identify Source** – Determine the origin of the information (LLM response, documentation, code, etc.)
2. **Extract Key Concepts** – Pull out the main ideas and terminology using pattern matching
3. **Generate Summary** – Create a brief, understandable overview
4. **Capture Examples** – Record real-world illustrations (code blocks, tables)
5. **Store Structured Knowledge** – Save in a standardized format for later use

## Supported Sources
- ✅ Large Language Model responses (LLM_RESPONSE)
- ✅ Project documentation - Markdown, RST, plain text (DOCUMENTATION)
- ✅ PDF files (if pypdf or pdfplumber is installed)
- 🔄 Source code repositories (SOURCE_CODE - extractor not yet implemented)
- 🔄 Local project files (USER_INPUT, TOOL_OUTPUT, LOG, API_RESPONSE - extractors not yet implemented)

## Desired Output Structure (Implemented)
Every extracted knowledge item follows one consistent structure:

| Field | Description |
|------|-------------|
| **id** | Unique identifier (kobj_<uuid>) |
| **title** | Brief title/topic |
| **summary** | Concise description (1-2 sentences) |
| **content** | Full extracted content |
| **source** | Original source attribution (file path, conversation ID, etc.) |
| **source_type** | Source type enum (LLM_RESPONSE, DOCUMENTATION, etc.) |
| **category** | Knowledge category (FACT, PROCEDURE, ALGORITHM, etc.) |
| **tags** | Searchable tags extracted from content |
| **confidence** | Preliminary confidence estimate (0-1) |
| **language** | Programming language if applicable |
| **related_entities** | Entity names/IDs mentioned |
| **related_knowledge_ids** | Links to other knowledge objects |
| **extracted_at** | Timestamp of extraction |
| **metadata** | Additional structured data |

## Knowledge Categories (Implemented)
- **FACT** - Verifiable facts
- **EXPLANATION** - How something works
- **PROCEDURE** - Step-by-step instructions
- **ALGORITHM** - Code implementations, algorithms
- **BEST_PRACTICE** - Recommended approaches
- **RECOMMENDATION** - Suggestions
- **WORKFLOW** - Multi-step processes
- **TROUBLESHOOTING** - Debugging, fixes
- **CONCEPT** - Core concepts, principles
- **DEFINITION** - Term definitions
- **EXAMPLE** - Illustrative examples
- **WARNING** - Cautions, important notes
- **REFERENCE** - Reference material, tables
- **ARCHITECTURE** - System design descriptions
- **OTHER** - Unclassified

## Core Components

### KnowledgeExtractionPipeline (`app/knowledge_extraction/pipeline.py`)
Main orchestrator that coordinates the complete extraction process:
- Source detection (auto-detect from file extension or explicit type)
- Dispatches to appropriate extractor
- Post-processes results (enriches metadata)
- Tracks statistics
- Batch extraction support
- File-based extraction support

### ExtractorRegistry (`app/knowledge_extraction/extractors.py`)
Manages and dispatches extractors:
- Register/unregister extractors at runtime
- Auto-detect extractor from file extension
- Extensible architecture for new sources

### LLMExtractor (`app/knowledge_extraction/llm_extractor.py`)
Extracts knowledge from LLM responses:
- Facts, explanations, procedures
- Algorithms and code blocks
- Best practices and recommendations
- Workflows and troubleshooting
- Warnings and concepts
- Ignores conversational filler (greetings, pleasantries)
- Handles indented content from triple-quoted strings
- Extracts structured sections (markdown headers, bullet lists)
- Extracts key-value pairs (definitions, parameters)

### DocumentExtractor (`app/knowledge_extraction/doc_extractor.py`)
Extracts knowledge from documentation files:
- Markdown (.md, .markdown), RST, plain text
- PDF (with pypdf or pdfplumber)
- Hierarchical section parsing
- Code block extraction with language detection
- Markdown table extraction
- Admonition extraction (GitHub-style, Sphinx-style, custom)
- Category inference from headings
- Tag extraction from technical keywords

## Architecture

### Extensibility
The architecture makes it easy to add new extractors:
1. Subclass `Extractor` base class
2. Implement `extract()` method
3. Define `source_type` and `supported_extensions`
4. Register with `ExtractorRegistry`

No large if/else chains - source-specific logic is isolated in each extractor.

### Integration
The pipeline is reusable by any capability:
- **Knowledge Acquisition** - For capturing new knowledge
- **Knowledge Base** - For populating storage
- **Autonomous Learning** - For learning from observations
- **Memory** - For storing extracted knowledge
- **Planning** - For retrieving relevant knowledge
- **Reflection** - For analyzing past work
- **Software Engineering** - For capturing technical knowledge
- **Tool Ecosystem** - For extracting tool outputs

## Usage Examples

### Extract from LLM Response
```python
from app.knowledge_extraction import pipeline, SourceType

llm_response = """
Fact: Python uses indentation for code blocks.
Best practice: Always use 4 spaces for indentation.

```python
def hello():
    print("Hello")
```
"""

result = pipeline.extract(llm_response, "conv_123", SourceType.LLM_RESPONSE)
for obj in result.knowledge_objects:
    print(f"{obj.category.value}: {obj.title}")
```

### Extract from Documentation File
```python
result = pipeline.extract_from_file("docs/api_reference.md")
for obj in result.knowledge_objects:
    print(f"Section: {obj.title} ({obj.category.value})")
```

### Batch Extraction
```python
items = [
    {"content": "...", "source": "src1", "source_type": SourceType.LLM_RESPONSE},
    {"content": "...", "source": "doc.md", "source_type": SourceType.DOCUMENTATION},
]
results = pipeline.extract_batch(items)
```

### Add Custom Extractor
```python
from app.knowledge_extraction import Extractor, registry, SourceType

class CustomExtractor(Extractor):
    source_type = SourceType.SOURCE_CODE
    supported_extensions = [".py", ".js"]

    def extract(self, content, source, **context):
        # Custom extraction logic
        return result

registry.register(CustomExtractor())
```

## Error Handling
- Invalid input handled gracefully (empty content, malformed input)
- Unsupported sources return meaningful error information
- File reading errors (encoding, missing files) handled
- Parsing failures don't crash the pipeline
- Each extraction is independent - batch continues on partial failure

## Current Limitations
1. **No validation** - Confidence is an extraction estimate only; validation happens later
2. **No ranking** - Knowledge objects are not ranked by relevance
3. **No retrieval** - This capability only EXTRACTS; retrieval is separate
4. **No consolidation** - Duplicate detection is basic (exact content matching)
5. **Source code extraction not implemented** - Planned for future
6. **PDF extraction optional** - Requires pypdf or pdfplumber package

## Success Criteria Met
✅ End-to-end Knowledge Extraction Pipeline fully functional
✅ Structured knowledge objects consistently generated
✅ LLM responses extracted into structured knowledge
✅ Markdown documentation extracted into structured knowledge
✅ PDF extraction works (if PDF support exists)
✅ Errors handled gracefully
✅ Architecture modular and extensible
✅ Existing architecture compatible
✅ Tests pass (30 tests)
✅ Documentation updated

## Testing
Run tests with:
```bash
python -m pytest tests/test_knowledge_extraction.py -v
```

Test coverage includes:
- Data model serialization/deserialization
- LLM extraction (facts, code, procedures, warnings, filler removal)
- Documentation extraction (sections, code blocks, tables, admonitions)
- Category inference from headings
- File-based extraction
- Pipeline auto-detection
- Batch extraction
- Extensibility (custom extractors)
- Integration workflows

## Future Enhancements (Planned)
- Source code extractor (AST-based)
- Automatic diagram extraction
- Code pattern extraction
- Architecture pattern extraction
- Multi-document extraction
- Automatic tagging with ML
- Concept relationship graph
- Duplicate detection (semantic)
- Confidence calibration
- Extraction scheduler for periodic runs
- Knowledge extraction UI for monitoring

---

*Last Updated: 2026-07-31 - Implementation Complete*