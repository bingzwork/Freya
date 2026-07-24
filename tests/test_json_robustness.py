"""Tests for JSON Robustness Utilities.

This module tests the JSON validation and extraction utilities that ensure
the model returns valid JSON when requested.
"""

import json
import pytest

from app.intent.json_utils import (
    JSONValidationError,
    JSONExtractionError,
    JSONValidationResult,
    JSONSchema,
    JSONValidator,
    validate_json,
    extract_json,
)


class TestJSONValidationResult:
    """Test JSONValidationResult dataclass."""

    def test_valid_result(self):
        """Test valid result creation."""
        result = JSONValidationResult(
            valid=True,
            data={"key": "value"},
        )
        assert result.valid is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_invalid_result(self):
        """Test invalid result creation."""
        result = JSONValidationResult(
            valid=False,
            error="Invalid JSON",
            raw_response='{"key": "value"',
        )
        assert result.valid is False
        assert result.error == "Invalid JSON"
        assert result.raw_response == '{"key": "value"'

    def test_repr(self):
        """Test string representation."""
        result = JSONValidationResult(valid=True, data={"test": 123})
        repr_str = repr(result)
        assert "JSONValidationResult" in repr_str
        assert "valid=True" in repr_str


class TestJSONSchema:
    """Test JSONSchema dataclass."""

    def test_default_schema(self):
        """Test default schema creation."""
        schema = JSONSchema()
        assert schema.required_fields == []
        assert schema.field_types == {}

    def test_custom_schema(self):
        """Test custom schema creation."""
        schema = JSONSchema(
            required_fields=["name", "age"],
            field_types={"name": str, "age": int},
        )
        assert schema.required_fields == ["name", "age"]
        assert schema.field_types == {"name": str, "age": int}


class TestJSONValidator:
    """Test JSONValidator class."""

    def test_validate_valid_json(self):
        """Test validation of valid JSON."""
        result = JSONValidator.validate('{"key": "value"}')
        assert result.valid is True
        assert result.data == {"key": "value"}

    def test_validate_invalid_json(self):
        """Test validation of invalid JSON."""
        result = JSONValidator.validate('{"key": "value"')
        assert result.valid is False
        assert result.error is not None

    def test_validate_with_schema(self):
        """Test validation with schema."""
        schema = JSONSchema(
            required_fields=["name"],
            field_types={"name": str},
        )
        result = JSONValidator.validate('{"name": "test"}', schema)
        assert result.valid is True

    def test_validate_missing_required_field(self):
        """Test validation with missing required field."""
        schema = JSONSchema(required_fields=["name"])
        result = JSONValidator.validate('{"age": 25}', schema)
        assert result.valid is False
        assert "Missing required field: name" in result.error

    def test_validate_wrong_field_type(self):
        """Test validation with wrong field type."""
        schema = JSONSchema(field_types={"age": int})
        result = JSONValidator.validate('{"age": "25"}', schema)
        assert result.valid is False
        assert "expected int" in result.error

    def test_validate_non_dict(self):
        """Test validation of non-dict JSON."""
        schema = JSONSchema(required_fields=["name"])
        result = JSONValidator.validate('["item1", "item2"]', schema)
        assert result.valid is False


class TestJSONExtraction:
    """Test JSON extraction from text."""

    def test_extract_plain_json(self):
        """Test extraction of plain JSON."""
        text = '{"key": "value"}'
        result = extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_with_text_before(self):
        """Test extraction of JSON with text before."""
        text = 'Here is the answer: {"key": "value"}'
        result = extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_with_text_after(self):
        """Test extraction of JSON with text after."""
        text = '{"key": "value"}\nThis is the JSON you requested.'
        result = extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_with_text_both_sides(self):
        """Test extraction of JSON with text on both sides."""
        text = 'Here is: {"key": "value"} and more text'
        result = extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_from_markdown_block(self):
        """Test extraction of JSON from markdown code block."""
        text = "```json\n{\"key\": \"value\"}\n```"
        result = extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_from_markdown_block_no_language(self):
        """Test extraction of JSON from markdown code block without language."""
        text = "```\n{\"key\": \"value\"}\n```"
        result = extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_nested_json(self):
        """Test extraction of nested JSON."""
        json_str = '{"outer": {"inner": "value"}}'
        result = extract_json(json_str)
        assert result == json_str

    def test_extract_json_array(self):
        """Test extraction of JSON array."""
        text = '["item1", "item2"]'
        result = extract_json(text)
        assert result == text

    def test_extract_returns_none_for_no_json(self):
        """Test that extraction returns None when no JSON is found."""
        text = "This is just plain text with no JSON"
        result = extract_json(text)
        assert result is None

    def test_extract_empty_string(self):
        """Test extraction of empty string."""
        result = extract_json("")
        assert result is None

    def test_extract_none(self):
        """Test extraction of None."""
        result = extract_json(None)
        assert result is None


class TestValidateJSON:
    """Test validate_json function."""

    def test_validate_simple_object(self):
        """Test validation of simple object."""
        result = validate_json('{"key": "value"}')
        assert result.valid is True
        assert result.data == {"key": "value"}

    def test_validate_with_schema(self):
        """Test validation with schema."""
        schema = JSONSchema(required_fields=["name"])
        result = validate_json('{"name": "test"}', schema)
        assert result.valid is True

    def test_validate_missing_field(self):
        """Test validation with missing field."""
        schema = JSONSchema(required_fields=["name"])
        result = validate_json('{"age": 25}', schema)
        assert result.valid is False


class TestIsValidJSON:
    """Test _is_valid_json static method."""

    def test_valid_json(self):
        """Test valid JSON detection."""
        assert JSONValidator._is_valid_json('{"key": "value"}') is True
        assert JSONValidator._is_valid_json('[1, 2, 3]') is True
        assert JSONValidator._is_valid_json('"string"') is True
        assert JSONValidator._is_valid_json('123') is True
        assert JSONValidator._is_valid_json('true') is True
        assert JSONValidator._is_valid_json('null') is True

    def test_invalid_json(self):
        """Test invalid JSON detection."""
        assert JSONValidator._is_valid_json('{"key": "value"') is False
        assert JSONValidator._is_valid_json('not json') is False
        assert JSONValidator._is_valid_json('') is False


class TestEdgeCases:
    """Test edge cases and complex scenarios."""

    def test_json_with_newlines(self):
        """Test JSON with newlines."""
        text = '{\n  "key": "value"\n}'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["key"] == "value"

    def test_json_with_escaped_quotes(self):
        """Test JSON with escaped quotes."""
        text = '{"key": "value with \\"quotes\\""}'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert '"' in data["key"]

    def test_multiple_json_blocks(self):
        """Test extraction with multiple JSON blocks (should get first)."""
        text = '{"first": 1}\n{"second": 2}'
        result = extract_json(text)
        # Should get the first complete JSON block
        assert result == '{"first": 1}'

    def test_json_in_list_form(self):
        """Test JSON in list form."""
        text = "Here are the results: [1, 2, 3]"
        result = extract_json(text)
        assert result == "[1, 2, 3]"

    def test_html_in_json(self):
        """Test JSON containing HTML."""
        json_str = '{"html": "<div>content</div>"}'
        result = extract_json(json_str)
        assert result == json_str

    def test_unicode_in_json(self):
        """Test JSON with Unicode characters."""
        json_str = '{"message": "Hello 世界"}'
        result = extract_json(json_str)
        assert result == json_str
