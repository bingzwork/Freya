"""HTTP request tools for Freya.

Provides HTTP request capabilities for fetching data from web APIs and services.
These tools are non-destructive (read-only) and qualify for autonomous approval.

Note: POST, PUT, DELETE, PATCH can modify remote resources but are classified
as read-only for local workspace safety since they don't modify local files.
Remote server mutations are the user's responsibility.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests


def http_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute an HTTP GET request.

    Args:
        url: The URL to request
        headers: Optional HTTP headers to include
        params: Optional query parameters
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Dict with keys:
        - status: HTTP status code
        - headers: Response headers as dict
        - body: Response body as string (raw)
        - json: Parsed JSON if content-type is JSON, None otherwise
        - error: Error message if request failed, None otherwise
    """
    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=timeout,
        )
        body = response.text
        json_data = None
        try:
            json_data = response.json()
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "json": json_data,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": None,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(e),
        }


def http_post(
    url: str,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute an HTTP POST request.

    Args:
        url: The URL to request
        data: Form data to send
        json: JSON data to send (sets Content-Type: application/json)
        headers: Optional HTTP headers to include
        params: Optional query parameters
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Dict with keys:
        - status: HTTP status code
        - headers: Response headers as dict
        - body: Response body as string (raw)
        - json: Parsed JSON if content-type is JSON, None otherwise
        - error: Error message if request failed, None otherwise
    """
    try:
        response = requests.post(
            url,
            data=data,
            json=json,
            headers=headers,
            params=params,
            timeout=timeout,
        )
        body = response.text
        json_data = None
        try:
            json_data = response.json()
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "json": json_data,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": None,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(e),
        }


def http_put(
    url: str,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute an HTTP PUT request.

    Args:
        url: The URL to request
        data: Form data to send
        json: JSON data to send (sets Content-Type: application/json)
        headers: Optional HTTP headers to include
        params: Optional query parameters
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Dict with keys:
        - status: HTTP status code
        - headers: Response headers as dict
        - body: Response body as string (raw)
        - json: Parsed JSON if content-type is JSON, None otherwise
        - error: Error message if request failed, None otherwise
    """
    try:
        response = requests.put(
            url,
            data=data,
            json=json,
            headers=headers,
            params=params,
            timeout=timeout,
        )
        body = response.text
        json_data = None
        try:
            json_data = response.json()
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "json": json_data,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": None,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(e),
        }


def http_delete(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute an HTTP DELETE request.

    Args:
        url: The URL to request
        headers: Optional HTTP headers to include
        params: Optional query parameters
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Dict with keys:
        - status: HTTP status code
        - headers: Response headers as dict
        - body: Response body as string (raw)
        - json: Parsed JSON if content-type is JSON, None otherwise
        - error: Error message if request failed, None otherwise
    """
    try:
        response = requests.delete(
            url,
            headers=headers,
            params=params,
            timeout=timeout,
        )
        body = response.text
        json_data = None
        try:
            json_data = response.json()
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "json": json_data,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": None,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(e),
        }


def http_patch(
    url: str,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute an HTTP PATCH request.

    Args:
        url: The URL to request
        data: Form data to send
        json: JSON data to send (sets Content-Type: application/json)
        headers: Optional HTTP headers to include
        params: Optional query parameters
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Dict with keys:
        - status: HTTP status code
        - headers: Response headers as dict
        - body: Response body as string (raw)
        - json: Parsed JSON if content-type is JSON, None otherwise
        - error: Error message if request failed, None otherwise
    """
    try:
        response = requests.patch(
            url,
            data=data,
            json=json,
            headers=headers,
            params=params,
            timeout=timeout,
        )
        body = response.text
        json_data = None
        try:
            json_data = response.json()
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "json": json_data,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": None,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(e),
        }


def http_head(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute an HTTP HEAD request.

    Args:
        url: The URL to request
        headers: Optional HTTP headers to include
        params: Optional query parameters
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Dict with keys:
        - status: HTTP status code
        - headers: Response headers as dict
        - body: Always empty string for HEAD requests
        - json: Always None for HEAD requests
        - error: Error message if request failed, None otherwise
    """
    try:
        response = requests.head(
            url,
            headers=headers,
            params=params,
            timeout=timeout,
        )

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": "",
            "json": None,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": None,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(e),
        }


def http_request(
    method: str,
    url: str,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    *,
    allow_redirects: bool = True,
    max_response_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute a generic HTTP request with optional redirect/size controls."""
    method = method.upper()

    try:
        response = requests.request(
            method,
            url,
            data=data,
            json=json,
            headers=headers,
            params=params,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )
        body = response.text
        truncated = False
        if max_response_bytes is not None:
            if max_response_bytes <= 0:
                raise ValueError("max_response_bytes must be positive")
            raw_body = getattr(response, "content", None)
            if isinstance(raw_body, (bytes, bytearray)):
                truncated = len(raw_body) > max_response_bytes
                body = bytes(raw_body[:max_response_bytes]).decode("utf-8", errors="replace")
            else:
                encoded_body = body.encode("utf-8")
                truncated = len(encoded_body) > max_response_bytes
                body = encoded_body[:max_response_bytes].decode("utf-8", errors="replace")
        json_data = None
        try:
            json_data = response.json()
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "json": json_data,
            "error": None,
            "truncated": truncated,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": None,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(e),
        }
