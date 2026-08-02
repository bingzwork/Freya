"""Patch Generator for generating code patches from issue descriptions.

This module provides functionality to generate code patches (in the form of file operations)
based on natural language descriptions of issues (e.g., requirement gaps, test failures,
code quality issues, etc.) using the agent's LLM.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any
import uuid

from app.core.logger import logger


@dataclass
class FileOperation:
    """Represents a file operation to be applied as part of a patch."""
    operation: str  # "create", "modify", "delete"
    file_path: str
    content: Optional[str] = None  # For create and modify operations
    original_content: Optional[str] = None  # For modify operations (to show what was replaced)
    line_range: Optional[tuple[int, int]] = None  # For modify operations (start, end line numbers, 1-indexed inclusive)


@dataclass
class Patch:
    """Represents a collection of file operations to fix an issue."""
    patch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    operations: List[FileOperation] = field(default_factory=list)
    # Metadata for logging and debugging
    issue_description: str = ""
    issue_type: str = ""  # e.g., "requirement_gap", "test_failure", "quality_issue", "documentation_issue"
    generated_by: str = "PatchGenerator"

    def to_dict(self) -> dict:
        """Convert the patch to a dictionary representation."""
        return {
            "patch_id": self.patch_id,
            "description": self.description,
            "issue_description": self.issue_description,
            "issue_type": self.issue_type,
            "generated_by": self.generated_by,
            "operations": [
                {
                    "operation": op.operation,
                    "file_path": op.file_path,
                    "content": op.content,
                    "original_content": op.original_content,
                    "line_range": op.line_range,
                }
                for op in self.operations
            ],
        }


class PatchGenerator:
    """Generates code patches from issue descriptions using an LLM."""

    def __init__(self, agent=None):
        """Initialize the patch generator.

        Args:
            agent: The FreyaAgent instance, used to access the LLM and other components.
        """
        self.agent = agent
        self.llm = agent.llm if agent else None

    def generate_patch(
        self,
        issue_description: str,
        issue_type: str,
        context: Optional[Dict[str, Any]] = None,
        file_paths: Optional[List[str]] = None,
    ) -> Optional[Patch]:
        """Generate a patch to fix the given issue.

        Args:
            issue_description: Description of the issue to fix.
            issue_type: Type of issue (e.g., "requirement_gap", "test_failure").
            context: Additional context (e.g., test output, code snippets).
            file_paths: List of file paths that are relevant to the issue.

        Returns:
            A Patch object containing the suggested fixes, or None if generation failed.
        """
        if not self.llm:
            logger.warning("[PatchGenerator] LLM not available, cannot generate patch")
            return None

        context = context or {}
        file_paths = file_paths or []

        # Prepare the prompt for the LLM
        prompt = self._build_patch_prompt(
            issue_description=issue_description,
            issue_type=issue_type,
            context=context,
            file_paths=file_paths,
        )

        try:
            response = self.llm.ask(prompt)
            patch = self._parse_llm_response(response, issue_description, issue_type)
            return patch
        except Exception as e:
            logger.error(f"[PatchGenerator] Failed to generate patch: {e}")
            return None

    def _build_patch_prompt(
        self,
        issue_description: str,
        issue_type: str,
        context: Dict[str, Any],
        file_paths: List[str],
    ) -> str:
        """Build a prompt for the LLM to generate a patch."""
        # We'll ask the LLM to generate a unified diff or a list of file operations.
        # For simplicity, we'll ask for a unified diff and then parse it.
        # However, generating a valid diff is complex. Alternatively, we can ask for
        # the new content of entire files.

        # We'll ask the LLM to provide the new content for each file that needs to be changed.
        prompt = f"""You are an expert software engineer tasked with generating a patch to fix a specific issue.

ISSUE TYPE: {issue_type}
ISSUE DESCRIPTION:
{issue_description}

CONTEXT:
"""

        # Add relevant context
        if "test_output" in context:
            prompt += f"\nTest Output:\n{context['test_output']}\n"
        if "code_snippets" in context:
            prompt += f"\nCode Snippets:\n{context['code_snippets']}\n"
        if "file_contents" in context:
            for file_path, content in context["file_contents"].items():
                prompt += f"\nFile: {file_path}\n```\n{content}\n```\n"

        # Add file paths to focus on
        if file_paths:
            prompt += f"\nRelevant Files:\n"
            for fp in file_paths:
                prompt += f"- {fp}\n"

        prompt += """
TASK:
Generate a patch that fixes the issue. For each file that needs to be changed, provide:
1. The file path
2. The complete new content for the file (if the file should be modified or created)
3. If the file should be deleted, indicate so.

Format your response as a JSON object with the following structure:
{
  "patches": [
    {
      "file_path": "path/to/file.py",
      "operation": "modify",  // "create", "modify", or "delete"
      "content": "// new file content here (for create/modify)"
      // For delete, content can be empty or omitted
    }
  ],
  "explanation": "Brief explanation of the changes made"
}

IMPORTANT:
- Only include files that need to be changed to fix the issue.
- For modify operations, provide the FULL new file content.
- Ensure the code is syntactically correct and follows the project's style.
- Do not include any extra text outside the JSON.
"""

        return prompt

    def _parse_llm_response(
        self, response: str, issue_description: str, issue_type: str
    ) -> Optional[Patch]:
        """Parse the LLM's response into a Patch object."""
        import json
        import re

        try:
            # Extract JSON from the response
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                logger.error("[PatchGenerator] No JSON found in LLM response")
                return None

            data = json.loads(json_match.group())

            # Validate the expected structure
            if "patches" not in data:
                logger.error("[PatchGenerator] 'patches' key not found in LLM response")
                return None

            operations = []
            for patch_data in data["patches"]:
                file_path = patch_data.get("file_path")
                operation = patch_data.get("operation")
                content = patch_data.get("content")

                if not file_path or not operation:
                    continue

                # Validate operation
                if operation not in ["create", "modify", "delete"]:
                    continue

                op = FileOperation(
                    operation=operation,
                    file_path=file_path,
                    content=content if operation in ["create", "modify"] else None,
                )
                operations.append(op)

            if not operations:
                logger.warning("[PatchGenerator] No valid operations parsed from LLM response")
                return None

            patch = Patch(
                description=data.get("explanation", "Patch generated to fix issue"),
                operations=operations,
                issue_description=issue_description,
                issue_type=issue_type,
            )

            return patch
        except json.JSONDecodeError as e:
            logger.error(f"[PatchGenerator] Failed to parse JSON from LLM response: {e}")
            return None
        except Exception as e:
            logger.error(f"[PatchGenerator] Unexpected error parsing LLM response: {e}")
            return None

    def generate_patch_from_requirement_gap(
        self,
        requirement_verification: Any,  # RequirementVerification object
        work_output: str,
        work_context: dict,
    ) -> Optional[Patch]:
        """Generate a patch to address a requirement gap.

        Args:
            requirement_verification: The requirement verification that failed.
            work_output: The output/work product from the task.
            work_context: Context about the work.

        Returns:
            A Patch object or None.
        """
        issue_desc = f"""
Requirement: {requirement_verification.requirement_description}
Status: {requirement_verification.status.value}
Gaps: {', '.join(requirement_verification.gaps)}
Evidence: {', '.join(requirement_verification.evidence)}
"""

        context = {
            "work_output": work_output[:2000],  # Limit size
            "work_context": work_context,
            "requirement_details": {
                "id": requirement_verification.requirement_id,
                "description": requirement_verification.requirement_description,
                "acceptance_criteria": [],  # We don't have access to the original requirement object here
            },
        }

        return self.generate_patch(
            issue_description=issue_desc,
            issue_type="requirement_gap",
            context=context,
        )

    def generate_patch_from_test_failure(
        self,
        validation_result: Any,  # ValidationResult object for a failed test
        work_context: dict,
    ) -> Optional[Patch]:
        """Generate a patch to fix a failing test.

        Args:
            validation_result: The validation result that failed (should be a test failure).
            work_context: Context about the work.

        Returns:
            A Patch object or None.
        """
        if validation_result.status.value != "failed":
            return None

        issue_desc = f"""
Test: {validation_result.check_name}
Type: {validation_result.check_type}
Error: {validation_result.stderr}
Stdout: {validation_result.stdout}
"""

        context = {
            "test_output": f"STDERR: {validation_result.stderr}\nSTDOUT: {validation_result.stdout}",
            "validation_result": {
                "check_name": validation_result.check_name,
                "check_type": validation_result.check_type,
                "stdout": validation_result.stdout,
                "stderr": validation_result.stderr,
                "return_code": validation_result.return_code,
            },
        }

        return self.generate_patch(
            issue_description=issue_desc,
            issue_type="test_failure",
            context=context,
        )

    def generate_patch_from_quality_issue(
        self,
        quality_issue: Any,  # QualityIssue object
        file_content: str,
    ) -> Optional[Patch]:
        """Generate a patch to fix a code quality issue.

        Args:
            quality_issue: The quality issue to fix.
            file_content: The current content of the file.

        Returns:
            A Patch object or None.
        """
        issue_desc = f"""
Quality Issue: {quality_issue.title}
Description: {quality_issue.description}
File: {quality_issue.file_path}
Line: {quality_issue.line_number}
Suggestion: {quality_issue.suggestion}
"""

        context = {
            "file_content": file_content,
            "quality_issue": {
                "title": quality_issue.title,
                "description": quality_issue.description,
                "line_number": quality_issue.line_number,
                "suggestion": quality_issue.suggestion,
            },
        }

        return self.generate_patch(
            issue_description=issue_desc,
            issue_type="quality_issue",
            context=context,
            file_paths=[quality_issue.file_path] if quality_issue.file_path else [],
        )

    def generate_patch_from_documentation_issue(
        self,
        doc_check_result: Any,  # DocCheckResult object
    ) -> Optional[Patch]:
        """Generate a patch to fix a documentation issue.

        Args:
            doc_check_result: The documentation check result that failed.

        Returns:
            A Patch object or None.
        """
        issue_desc = f"""
Documentation Check: {doc_check_result.check_name}
Type: {doc_check_result.check_type}
Issues: {', '.join(doc_check_result.issues)}
Suggestions: {', '.join(doc_check_result.suggestions)}
"""

        context = {
            "doc_check_result": {
                "check_name": doc_check_result.check_name,
                "check_type": doc_check_result.check_type,
                "issues": doc_check_result.issues,
                "suggestions": doc_check_result.suggestions,
                "details": doc_check_result.details,
            },
        }

        # For documentation issues, we might need to modify specific files (like README.md)
        # We don't have the file content here, but we can infer from the check type.
        file_paths = []
        if doc_check_result.check_type == "readme":
            file_paths = ["README.md", "README", "readme.md", "readme"]
        elif doc_check_result.check_type == "implementation_status":
            file_paths = ["IMPLEMENTATION_STATUS.md"]
        elif doc_check_result.check_type == "roadmap":
            file_paths = ["ROADMAP.md"]
        elif doc_check_result.check_type == "self_evaluation":
            file_paths = ["SELF_EVALUATION.md"]
        elif doc_check_result.check_type in ["inline_docs", "type_hints"]:
            # These would be handled per file in the issue details, but we don't have that here.
            # We'll rely on the LLM to figure out which files need changes based on the issue description.
            pass

        return self.generate_patch(
            issue_description=issue_desc,
            issue_type="documentation_issue",
            context=context,
            file_paths=file_paths,
        )


# Convenience function for easy access
def generate_patch(
    issue_description: str,
    issue_type: str,
    context: Optional[Dict[str, Any]] = None,
    file_paths: Optional[List[str]] = None,
    agent=None,
) -> Optional[Patch]:
    """Convenience function to generate a patch.

    Args:
        issue_description: Description of the issue to fix.
        issue_type: Type of issue.
        context: Additional context.
        file_paths: List of relevant file paths.
        agent: The FreyaAgent instance.

    Returns:
        A Patch object or None.
    """
    generator = PatchGenerator(agent=agent)
    return generator.generate_patch(
        issue_description=issue_description,
        issue_type=issue_type,
        context=context,
        file_paths=file_paths,
    )