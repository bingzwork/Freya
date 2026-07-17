"""Tests for HTTP request tools."""

import pytest
from unittest.mock import patch


class MockResponse:
    """Mock requests.Response object."""

    def __init__(self, status_code, text, headers=None, json_data=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._json_data = json_data

    def json(self):
        return self._json_data


# Import after MockResponse to avoid circular issues
from app.tools.http_tools import (
    http_get,
    http_post,
    http_put,
    http_delete,
    http_patch,
    http_head,
    http_request,
)
import requests


def test_http_get_success():
    """Test successful HTTP GET request."""
    with patch("app.tools.http_tools.requests.get") as mock_get:
        mock_response = MockResponse(
            200,
            '{"key": "value"}',
            {"Content-Type": "application/json"},
            {"key": "value"}
        )
        mock_get.return_value = mock_response

        result = http_get("https://api.example.com/data")

        assert result["status"] == 200
        assert result["body"] == '{"key": "value"}'
        assert result["json"] == {"key": "value"}
        assert result["error"] is None


def test_http_get_with_headers():
    """Test HTTP GET with custom headers."""
    with patch("app.tools.http_tools.requests.get") as mock_get:
        mock_response = MockResponse(
            200,
            "success",
            {"X-Custom": "header-value"},
        )
        mock_get.return_value = mock_response

        result = http_get(
            "https://api.example.com/data",
            headers={"Authorization": "Bearer token"}
        )

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer token"


def test_http_get_with_params():
    """Test HTTP GET with query parameters."""
    with patch("app.tools.http_tools.requests.get") as mock_get:
        mock_response = MockResponse(200, "success")
        mock_get.return_value = mock_response

        result = http_get(
            "https://api.example.com/data",
            params={"key": "value", "page": 1}
        )

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[1]["params"]["key"] == "value"
        assert call_args[1]["params"]["page"] == 1


def test_http_get_timeout():
    """Test HTTP GET with custom timeout."""
    with patch("app.tools.http_tools.requests.get") as mock_get:
        mock_response = MockResponse(200, "success")
        mock_get.return_value = mock_response

        result = http_get("https://api.example.com/data", timeout=60)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[1]["timeout"] == 60


def test_http_get_failure():
    """Test HTTP GET failure."""
    with patch("app.tools.http_tools.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError("Failed to connect")

        result = http_get("https://api.example.com/data")

        assert result["status"] is None
        assert result["error"] == "Failed to connect"
        assert result["body"] == ""


def test_http_post_success():
    """Test successful HTTP POST request."""
    with patch("app.tools.http_tools.requests.post") as mock_post:
        mock_response = MockResponse(
            201,
            '{"id": 1}',
            json_data={"id": 1}
        )
        mock_post.return_value = mock_response

        result = http_post(
            "https://api.example.com/data",
            json={"name": "test"}
        )

        assert result["status"] == 201
        assert result["json"] == {"id": 1}
        assert result["error"] is None


def test_http_post_form_data():
    """Test HTTP POST with form data."""
    with patch("app.tools.http_tools.requests.post") as mock_post:
        mock_response = MockResponse(200, "success")
        mock_post.return_value = mock_response

        result = http_post(
            "https://api.example.com/data",
            data={"key": "value"}
        )

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[1]["data"]["key"] == "value"


def test_http_put_success():
    """Test successful HTTP PUT request."""
    with patch("app.tools.http_tools.requests.put") as mock_put:
        mock_response = MockResponse(200, "updated")
        mock_put.return_value = mock_response

        result = http_put("https://api.example.com/data/1", json={"name": "updated"})

        assert result["status"] == 200
        assert result["error"] is None


def test_http_delete_success():
    """Test successful HTTP DELETE request."""
    with patch("app.tools.http_tools.requests.delete") as mock_delete:
        mock_response = MockResponse(204, "")
        mock_delete.return_value = mock_response

        result = http_delete("https://api.example.com/data/1")

        assert result["status"] == 204
        assert result["error"] is None


def test_http_patch_success():
    """Test successful HTTP PATCH request."""
    with patch("app.tools.http_tools.requests.patch") as mock_patch:
        mock_response = MockResponse(200, "patched")
        mock_patch.return_value = mock_response

        result = http_patch("https://api.example.com/data/1", json={"name": "patched"})

        assert result["status"] == 200
        assert result["error"] is None


def test_http_head_success():
    """Test successful HTTP HEAD request."""
    with patch("app.tools.http_tools.requests.head") as mock_head:
        mock_response = MockResponse(
            200,
            "",
            {"Content-Length": "1234"}
        )
        mock_head.return_value = mock_response

        result = http_head("https://api.example.com/data")

        assert result["status"] == 200
        assert result["body"] == ""
        assert result["json"] is None
        assert result["headers"]["Content-Length"] == "1234"


def test_http_request_get():
    """Test generic HTTP request with GET method."""
    with patch("app.tools.http_tools.requests.request") as mock_request:
        mock_response = MockResponse(200, "success")
        mock_request.return_value = mock_response

        result = http_request("GET", "https://api.example.com/data")

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "GET"
        assert result["status"] == 200


def test_http_request_post():
    """Test generic HTTP request with POST method."""
    with patch("app.tools.http_tools.requests.request") as mock_request:
        mock_response = MockResponse(201, "created")
        mock_request.return_value = mock_response

        result = http_request(
            "POST",
            "https://api.example.com/data",
            json={"key": "value"}
        )

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "POST"
        assert result["status"] == 201


def test_http_request_lowercase_method():
    """Test generic HTTP request with lowercase method (should be uppercased)."""
    with patch("app.tools.http_tools.requests.request") as mock_request:
        mock_response = MockResponse(200, "success")
        mock_request.return_value = mock_response

        result = http_request("get", "https://api.example.com/data")

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "GET"


def test_non_json_response():
    """Test handling of non-JSON response."""
    with patch("app.tools.http_tools.requests.get") as mock_get:
        mock_response = MockResponse(
            200,
            "This is plain text",
            {"Content-Type": "text/plain"}
        )
        mock_get.return_value = mock_response

        result = http_get("https://api.example.com/text")

        assert result["status"] == 200
        assert result["body"] == "This is plain text"
        assert result["json"] is None


def test_empty_response():
    """Test handling of empty response."""
    with patch("app.tools.http_tools.requests.get") as mock_get:
        mock_response = MockResponse(204, "")
        mock_get.return_value = mock_response

        result = http_get("https://api.example.com/empty")

        assert result["status"] == 204
        assert result["body"] == ""
        assert result["json"] is None


def test_all_http_methods_importable():
    """Test that all HTTP methods are importable and callable."""
    from app.tools import (
        http_get,
        http_post,
        http_put,
        http_delete,
        http_patch,
        http_head,
        http_request,
    )

    assert callable(http_get)
    assert callable(http_post)
    assert callable(http_put)
    assert callable(http_delete)
    assert callable(http_patch)
    assert callable(http_head)
    assert callable(http_request)
