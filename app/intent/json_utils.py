"""JSON Robustness Utilities.

This module provides utilities for ensuring the model returns valid JSON
when requested. It includes validation, retry mechanisms, and extraction
for handling model responses that may not follow instructions perfectly.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

from app.core.logger import logger
from app.core.llm import LLM
try:
    from app.core.llm import LLMError
except ImportError:
    LLMError = Exception  # Fallback if LLMError is not defined


class JSONValidationError(Exception):
    """Exception raised when JSON validation fails."""
    pass


class JSONExtractionError(Exception):
    """Exception raised when JSON extraction fails."""
    pass


@dataclass
class JSONValidationResult:
    """Result of JSON validation."""
    valid: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None

    def __repr__(self) -> str:
        if self.valid:
            return f"JSONValidationResult(valid=True, data={type(self.data).__name__})"
        return f"JSONValidationResult(valid=False, error={self.error})"


@dataclass
class JSONSchema:
    """Simple schema definition for JSON validation."""
    required_fields: List[str] = None
    field_types: Dict[str, type] = None

    def __post_init__(self):
        if self.required_fields is None:
            self.required_fields = []
        if self.field_types is None:
            self.field_types = {}


class JSONValidator:
    """Validates and extracts JSON from model responses.

    Provides robust handling for when the model doesn't perfectly
    follow JSON format instructions.
    """

    def __init__(self, llm: Optional[LLM] = None, max_retries: int = 3):
        """Initialize the JSON validator.

        Args:
            llm: The LLM instance to use for retries.
            max_retries: Maximum number of retry attempts.
        """
        self.llm = llm
        self.max_retries = max_retries

    @staticmethod
    def validate(response: str, schema: Optional[JSONSchema] = None) -> JSONValidationResult:
        """Validate a response as JSON.

        Args:
            response: The model response string.
            schema: Optional schema to validate against.

        Returns:
            JSONValidationResult with validation status.
        """
        try:
            # Try to parse as JSON directly
            data = json.loads(response)

            # Validate against schema if provided
            if schema:
                result = JSONValidator._validate_schema(data, schema)
                if not result.valid:
                    return result

            return JSONValidationResult(valid=True, data=data)

        except json.JSONDecodeError as e:
            # Try to extract JSON from response
            extracted = JSONValidator.extract_json(response)
            if extracted is not None:
                try:
                    data = json.loads(extracted)
                    if schema:
                        result = JSONValidator._validate_schema(data, schema)
                        if not result.valid:
                            return result
                    return JSONValidationResult(valid=True, data=data, raw_response=response)
                except json.JSONDecodeError:
                    pass

            return JSONValidationResult(
                valid=False,
                error=f"Invalid JSON: {str(e)}",
                raw_response=response,
            )

    @staticmethod
    def extract_json(text: str) -> Optional[str]:
        """Extract JSON from a text string.

        Handles common cases where the model wraps JSON in markdown
        code blocks or adds extra text.

        Args:
            text: The text to extract JSON from.

        Returns:
            The extracted JSON string, or None if not found.
        """
        if not text:
            return None

        # Try to find JSON in markdown code blocks
        # Pattern: ```json ... ``` or ``` ... ```
        json_block_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(json_block_pattern, text)
        if matches:
            for match in matches:
                if JSONValidator._is_valid_json(match):
                    return match

        # Try to find JSON at the start of the response
        # (model sometimes adds text after the JSON)
        # Look for the first { and find matching }
        first_brace = text.find("{")
        if first_brace >= 0:
            brace_count = 0
            json_start = first_brace
            for i in range(json_start, len(text)):
                if text[i] == "{":
                    brace_count += 1
                elif text[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        json_str = text[json_start:i+1]
                        if JSONValidator._is_valid_json(json_str):
                            return json_str
                        break

        # Try to find JSON array at the start of the response
        # Look for the first [ and find matching ]
        first_bracket = text.find("[")
        if first_bracket >= 0:
            bracket_count = 0
            json_start = first_bracket
            for i in range(json_start, len(text)):
                if text[i] == "[":
                    bracket_count += 1
                elif text[i] == "]":
                    bracket_count -= 1
                if bracket_count == 0:
                    json_str = text[json_start:i+1]
                    if JSONValidator._is_valid_json(json_str):
                        return json_str
                    break

        # Try to find JSON at the end of the response
        # (model sometimes adds text before the JSON)
        last_brace = text.rfind("}")
        last_bracket = text.rfind("]")

        # Check for object first (higher priority if both exist)
        if last_brace >= 0:
            # Find matching {
            brace_count = 0
            for i in range(last_brace, -1, -1):
                if text[i] == "}":
                    brace_count += 1
                elif text[i] == "{":
                    brace_count -= 1
                if brace_count == 0:
                    json_str = text[i:last_brace+1]
                    if JSONValidator._is_valid_json(json_str):
                        return json_str
                    break

        # Check for array
        if last_bracket >= 0:
            # Find matching [`
            bracket_count = 0
            for i in range(last_bracket, -1, -1):
                if text[i] == "]":
                    bracket_count += 1
                elif text[i] == "[":
                    bracket_count -= 1
                if bracket_count == 0:
                    json_str = text[i:last_bracket+1]
                    if JSONValidator._is_valid_json(json_str):
                        return json_str
                    break

        # Try to parse the whole text as JSON
        if JSONValidator._is_valid_json(text):
            return text

        return None

    @staticmethod
    def _is_valid_json(text: str) -> bool:
        """Check if a string is valid JSON."""
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False

    @staticmethod
    def _validate_schema(data: Any, schema: JSONSchema) -> JSONValidationResult:
        """Validate data against a schema."""
        if not isinstance(data, dict):
            return JSONValidationResult(
                valid=False,
                error=f"Expected dict, got {type(data).__name__}",
                data=data,
            )

        # Check required fields
        for field in schema.required_fields:
            if field not in data:
                return JSONValidationResult(
                    valid=False,
                    error=f"Missing required field: {field}",
                    data=data,
                )

        # Check field types
        for field, expected_type in schema.field_types.items():
            if field in data and not isinstance(data[field], expected_type):
                actual_type = type(data[field]).__name__
                return JSONValidationResult(
                    valid=False,
                    error=f"Field '{field}' expected {expected_type.__name__}, got {actual_type}",
                    data=data,
                )

        return JSONValidationResult(valid=True, data=data)

    def ask_for_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        schema: Optional[JSONSchema] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Ask the LLM for a JSON response with validation and retries.

        If the response is not valid JSON or doesn't match the schema,
        the LLM will be asked again with a reminder to use proper JSON.

        Args:
            prompt: The user prompt.
            system: Optional system prompt.
            schema: Optional schema to validate against.
            timeout: Optional timeout.

        Returns:
            The parsed JSON data.

        Raises:
            JSONValidationError: If JSON validation fails after all retries.
            LLMError: If there's an error communicating with the LLM.
        """
        if self.llm is None:
            raise ValueError("LLM instance is required for ask_for_json")

        last_error: Optional[str] = None

        for attempt in range(self.max_retries):
            # Build system prompt with JSON requirement
            effective_system = system or "You are Freya, an autonomous AI software engineer. Respond as a focused engineer."
            json_system = (
                f"{effective_system}\n\n"
                "IMPORTANT: Return ONLY valid JSON. Do not add any text before or after the JSON."
            )

            try:
                response = self.llm.ask(prompt, system=json_system, timeout=timeout)
                result = self.validate(response, schema)

                if result.valid:
                    logger.debug(f"[JSONValidator] Valid JSON received on attempt {attempt + 1}")
                    return result.data

                last_error = result.error
                logger.warning(f"[JSONValidator] Attempt {attempt + 1} failed: {last_error}")

                # If we have a raw response, try to show what went wrong
                if result.raw_response:
                    logger.debug(f"[JSONValidator] Raw response: {result.raw_response[:200]}...")

            except LLMError as e:
                last_error = str(e)
                logger.error(f"[JSONValidator] LLM error on attempt {attempt + 1}: {last_error}")
                raise JSONValidationError(f"LLM error: {last_error}")

        # All retries exhausted
        raise JSONValidationError(
            f"Failed to get valid JSON after {self.max_retries} attempts. "
            f"Last error: {last_error}"
        )

    @staticmethod
    def ensure_json_response(
        llm: LLM,
        prompt: str,
        system: Optional[str] = None,
        schema: Optional[JSONSchema] = None,
        max_retries: int = 3,
    ) -> Any:
        """Convenience function to get a JSON response from the LLM.

        Args:
            llm: The LLM instance.
            prompt: The user prompt.
            system: Optional system prompt.
            schema: Optional schema to validate against.
            max_retries: Maximum number of retry attempts.

        Returns:
            The parsed JSON data.

        Raises:
            JSONValidationError: If JSON validation fails after all retries.
        """
        validator = JSONValidator(llm=llm, max_retries=max_retries)
        return validator.ask_for_json(prompt, system, schema)


def validate_json(response: str, schema: Optional[JSONSchema] = None) -> JSONValidationResult:
    """Validate a response as JSON.

    Args:
        response: The model response string.
        schema: Optional schema to validate against.

    Returns:
        JSONValidationResult with validation status.
    """
    return JSONValidator.validate(response, schema)


def extract_json(text: str) -> Optional[str]:
    """Extract JSON from a text string.

    Args:
        text: The text to extract JSON from.

    Returns:
        The extracted JSON string, or None if not found.
    """
    return JSONValidator.extract_json(text)


def ensure_json(
    llm: LLM,
    prompt: str,
    system: Optional[str] = None,
    schema: Optional[JSONSchema] = None,
    max_retries: int = 3,
) -> Any:
    """Get a JSON response from the LLM with validation.

    Args:
        llm: The LLM instance.
        prompt: The user prompt.
        system: Optional system prompt.
        schema: Optional schema to validate against.
        max_retries: Maximum number of retry attempts.

    Returns:
        The parsed JSON data.

    Raises:
        JSONValidationError: If JSON validation fails after all retries.
    """
    return JSONValidator.ensure_json_response(llm, prompt, system, schema, max_retries)
