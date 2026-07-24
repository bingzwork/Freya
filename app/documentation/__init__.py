"""Documentation Automation for Freya AI.

This module provides automatic generation and updating of documentation
for the Freya project, including API docs, module docs, and change logs.
"""

from app.documentation.doc_generator import (
    DocumentationGenerator,
    DocType,
    DocFormat,
)
from app.documentation.doc_template import (
    DocumentationTemplate,
    TemplateSection,
)
from app.documentation.doc_store import (
    DocumentationStore,
    DocumentationEntry,
    DocStatus,
)
from app.documentation.change_log import (
    ChangeLog,
    ChangeEntry,
    ChangeType,
)

__all__ = [
    "DocumentationGenerator",
    "DocType",
    "DocFormat",
    "DocumentationTemplate",
    "TemplateSection",
    "DocumentationStore",
    "DocumentationEntry",
    "DocStatus",
    "ChangeLog",
    "ChangeEntry",
    "ChangeType",
]
