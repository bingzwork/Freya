"""Documentation templates for consistent documentation generation.

This module provides template definitions for various types of documentation.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class TemplateSection(Enum):
    """Standard sections in documentation templates."""
    TITLE = "title"
    OVERVIEW = "overview"
    INSTALLATION = "installation"
    USAGE = "usage"
    EXAMPLES = "examples"
    API_REFERENCE = "api_reference"
    CONFIGURATION = "configuration"
    ARCHITECTURE = "architecture"
    DEPENDENCIES = "dependencies"
    CHANGELOG = "changelog"
    LICENSE = "license"
    CONTRIBUTING = "contributing"
    FAQ = "faq"
    TROUBLESHOOTING = "troubleshooting"


@dataclass
class TemplateVariable:
    """A variable in a documentation template."""
    name: str
    default_value: str = ""
    required: bool = False
    description: str = ""


@dataclass
class DocumentationTemplate:
    """Represents a documentation template."""
    template_id: str = field(default_factory=lambda: f"template_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    content: str = ""
    variables: List[TemplateVariable] = field(default_factory=list)
    sections: List[TemplateSection] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    author: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def render(self, variables: Dict[str, str]) -> str:
        """Render the template with the given variables.

        Args:
            variables: Dictionary of variable names to values

        Returns:
            Rendered documentation content
        """
        content = self.content

        # Replace template variables
        for var_name, var_value in variables.items():
            # Support both {{var_name}} and {var_name} syntax
            content = content.replace(f"{{{{{var_name}}}}}", var_value)
            content = content.replace(f"{{{var_name}}}", var_value)

        return content

    def validate_variables(self, variables: Dict[str, str]) -> List[str]:
        """Validate that all required variables are provided.

        Args:
            variables: Dictionary of variable names to values

        Returns:
            List of missing required variable names
        """
        missing = []
        for var in self.variables:
            if var.required and var.name not in variables:
                missing.append(var.name)
        return missing

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "variables": [
                {"name": v.name, "default_value": v.default_value, "required": v.required, "description": v.description}
                for v in self.variables
            ],
            "sections": [s.value for s in self.sections],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "author": self.author,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentationTemplate":
        """Create from dictionary."""
        template = cls(
            template_id=data.get("template_id", f"template_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            content=data.get("content", ""),
            author=data.get("author", "system"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {}),
        )

        # Load variables
        for var_data in data.get("variables", []):
            var = TemplateVariable(
                name=var_data.get("name", ""),
                default_value=var_data.get("default_value", ""),
                required=var_data.get("required", False),
                description=var_data.get("description", ""),
            )
            template.variables.append(var)

        # Load sections
        for section_name in data.get("sections", []):
            try:
                template.sections.append(TemplateSection(section_name))
            except ValueError:
                pass

        return template


# Predefined templates

MODULE_TEMPLATE = DocumentationTemplate(
    name="Module Documentation",
    description="Template for module-level documentation",
    content="""# {{module_name}}

## Overview
{{module_overview}}

## API Reference

### Classes
{{classes}}

### Functions
{{functions}}

### Type Definitions
{{types}}
""",
    variables=[
        TemplateVariable("module_name", "", True, "Name of the module"),
        TemplateVariable("module_overview", "", True, "Overview of the module"),
        TemplateVariable("classes", "No classes documented.", False, "Class documentation"),
        TemplateVariable("functions", "No functions documented.", False, "Function documentation"),
        TemplateVariable("types", "No types documented.", False, "Type definitions"),
    ],
    sections=[
        TemplateSection.TITLE,
        TemplateSection.OVERVIEW,
        TemplateSection.API_REFERENCE,
    ],
)

CLASS_TEMPLATE = DocumentationTemplate(
    name="Class Documentation",
    description="Template for class-level documentation",
    content="""## {{class_name}}

{{class_description}}

**Bases:** {{bases}}

**Attributes:**
{{attributes}}

**Methods:**
{{methods}}
""",
    variables=[
        TemplateVariable("class_name", "", True, "Name of the class"),
        TemplateVariable("class_description", "", True, "Description of the class"),
        TemplateVariable("bases", "object", False, "Base classes"),
        TemplateVariable("attributes", "None", False, "Class attributes"),
        TemplateVariable("methods", "None", False, "Class methods"),
    ],
    sections=[
        TemplateSection.TITLE,
        TemplateSection.OVERVIEW,
    ],
)

FUNCTION_TEMPLATE = DocumentationTemplate(
    name="Function Documentation",
    description="Template for function-level documentation",
    content="""### {{function_name}}

```python
{{function_signature}}
```

{{function_description}}

**Parameters:**
{{parameters}}

**Returns:**
{{returns}}

**Raises:**
{{raises}}

**Examples:**
{{examples}}
""",
    variables=[
        TemplateVariable("function_name", "", True, "Name of the function"),
        TemplateVariable("function_signature", "", True, "Function signature (code)"),
        TemplateVariable("function_description", "", True, "Description of the function"),
        TemplateVariable("parameters", "None", False, "Parameter descriptions"),
        TemplateVariable("returns", "None", False, "Return value description"),
        TemplateVariable("raises", "None", False, "Exceptions that may be raised"),
        TemplateVariable("examples", "None", False, "Usage examples"),
    ],
    sections=[
        TemplateSection.TITLE,
        TemplateSection.OVERVIEW,
        TemplateSection.USAGE,
        TemplateSection.EXAMPLES,
    ],
)

README_TEMPLATE = DocumentationTemplate(
    name="README",
    description="Template for project README",
    content="""# {{project_name}}

{{project_description}}

## Badges

{{badges}}

## Features

{{features}}

## Installation

{{installation}}

## Quick Start

{{quick_start}}

## Usage

{{usage}}

## Configuration

{{configuration}}

## examples

{{examples}}

## API Reference

{{api_reference}}

## Contributing

{{contributing}}

## License

{{license}}
""",
    variables=[
        TemplateVariable("project_name", "", True, "Name of the project"),
        TemplateVariable("project_description", "", True, "Description of the project"),
        TemplateVariable("badges", "", False, "Status badges (CI, coverage, etc.)"),
        TemplateVariable("features", "", False, "List of project features"),
        TemplateVariable("installation", "", False, "Installation instructions"),
        TemplateVariable("quick_start", "", False, "Quick start guide"),
        TemplateVariable("usage", "", False, "Usage instructions"),
        TemplateVariable("configuration", "", False, "Configuration options"),
        TemplateVariable("examples", "", False, "Usage examples"),
        TemplateVariable("api_reference", "", False, "API reference"),
        TemplateVariable("contributing", "", False, "Contributing guidelines"),
        TemplateVariable("license", "", False, "License information"),
    ],
    sections=[
        TemplateSection.TITLE,
        TemplateSection.OVERVIEW,
        TemplateSection.INSTALLATION,
        TemplateSection.USAGE,
        TemplateSection.EXAMPLES,
        TemplateSection.API_REFERENCE,
        TemplateSection.CONTRIBUTING,
        TemplateSection.LICENSE,
    ],
)

CHANGELOG_TEMPLATE = DocumentationTemplate(
    name="Change Log",
    description="Template for change log entries",
    content="""# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Change Log](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

{{unreleased_changes}}

## [{{version}}] - {{date}}

### Added
{{added}}

### Changed
{{changed}}

### Fixed
{{fixed}}

### Deprecated
{{deprecated}}

### Removed
{{removed}}

### Security
{{security}}
""",
    variables=[
        TemplateVariable("version", "", True, "Version number"),
        TemplateVariable("date", "", True, "Release date"),
        TemplateVariable("unreleased_changes", "", False, "Unreleased changes"),
        TemplateVariable("added", "", False, "New features"),
        TemplateVariable("changed", "", False, "Changes in existing functionality"),
        TemplateVariable("fixed", "", False, "Bug fixes"),
        TemplateVariable("deprecated", "", False, "Deprecated features"),
        TemplateVariable("removed", "", False, "Removed features"),
        TemplateVariable("security", "", False, "Security fixes"),
    ],
    sections=[
        TemplateSection.TITLE,
        TemplateSection.CHANGELOG,
    ],
)

API_REFERENCE_TEMPLATE = DocumentationTemplate(
    name="API Reference",
    description="Template for API reference documentation",
    content="""# API Reference

## {{module_name}}

{{module_description}}

### Classes

{{classes}}

### Functions

{{functions}}

### Enums

{{enums}}

### Exceptions

{{exceptions}}
""",
    variables=[
        TemplateVariable("module_name", "", True, "Name of the module"),
        TemplateVariable("module_description", "", False, "Description of the module"),
        TemplateVariable("classes", "", False, "Class documentation"),
        TemplateVariable("functions", "", False, "Function documentation"),
        TemplateVariable("enums", "", False, "Enum documentation"),
        TemplateVariable("exceptions", "", False, "Exception documentation"),
    ],
    sections=[
        TemplateSection.TITLE,
        TemplateSection.OVERVIEW,
        TemplateSection.API_REFERENCE,
    ],
)


@dataclass
class TemplateRegistry:
    """Registry of documentation templates."""
    templates: Dict[str, DocumentationTemplate] = field(default_factory=dict)

    def __post_init__(self):
        self._register_builtin_templates()

    def _register_builtin_templates(self) -> None:
        """Register the built-in templates."""
        self.register(MODULE_TEMPLATE)
        self.register(CLASS_TEMPLATE)
        self.register(FUNCTION_TEMPLATE)
        self.register(README_TEMPLATE)
        self.register(CHANGELOG_TEMPLATE)
        self.register(API_REFERENCE_TEMPLATE)

    def register(self, template: DocumentationTemplate) -> None:
        """Register a template.

        Args:
            template: The template to register
        """
        self.templates[template.name] = template
        self.templates[template.template_id] = template

    def get(self, name: str) -> Optional[DocumentationTemplate]:
        """Get a template by name or ID.

        Args:
            name: The name or ID of the template

        Returns:
            The template if found, None otherwise
        """
        return self.templates.get(name)

    def list_templates(self) -> List[DocumentationTemplate]:
        """List all registered templates.

        Returns:
            List of templates
        """
        return list(self.templates.values())

    def remove(self, name: str) -> bool:
        """Remove a template.

        Args:
            name: The name or ID of the template to remove

        Returns:
            True if the template was found and removed, False otherwise
        """
        if name in self.templates:
            del self.templates[name]
            return True
        return False

    def create_from_preset(
        self,
        preset_name: str,
        **customizations,
    ) -> DocumentationTemplate:
        """Create a template from a preset with customizations.

        Args:
            preset_name: The name of the preset template
            **customizations: Customizations to apply

        Returns:
            A new template with the customizations
        """
        preset = self.get(preset_name)
        if not preset:
            raise ValueError(f"Unknown preset: {preset_name}")

        # Create a copy
        template_dict = preset.to_dict()
        template_dict.pop("template_id", None)  # Remove ID to get a new one

        # Apply customizations
        for key, value in customizations.items():
            if hasattr(preset, key):
                template_dict[key] = value

        return DocumentationTemplate.from_dict(template_dict)


# Module-level registry instance
registry = TemplateRegistry()
