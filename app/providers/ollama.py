"""Ollama LLM Provider.

This module provides the concrete implementation for the Ollama LLM provider,
which communicates with a local Ollama server via HTTP API.
"""

import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from app.providers.base import (
    BaseLLMProvider,
    Message,
    ProviderConfig,
    ProviderConnectionError,
    ProviderError,
    ProviderHealthStatus,
    ProviderModelNotFoundError,
    ProviderResponse,
    ProviderTimeoutError,
)
from app.core.logger import logger


class OllamaProvider(BaseLLMProvider):
    """LLM Provider for local Ollama server.

    Communicates with the Ollama server via its HTTP API (typically at http://localhost:11434).
    Supports both the /api/chat endpoint for chat-based interactions and /api/generate
    for direct generation.
    """

    provider_name = "ollama"

    def __init__(self, config: Optional[ProviderConfig] = None):
        """Initialize the Ollama provider.

        Args:
            config: Provider configuration. Defaults to local Ollama server settings.

        Raises:
            ProviderConfigurationError: If required configuration is missing.
        """
        if config is None:
            config = ProviderConfig(
                provider_name="ollama",
                model="qwen3:8b",
                base_url="http://localhost:11434",
                timeout=120.0,
            )

        super().__init__(config)
        self._client = OllamaClient(base_url=self.config.base_url, timeout=self.config.timeout)
        self._last_health_state: Optional[bool] = None

    @property
    def base_url(self) -> str:
        """Get the base URL of the Ollama server."""
        return self.config.base_url or "http://localhost:11434"

    @property
    def model(self) -> str:
        """Get the model name, with default fallback."""
        return self.config.model or "qwen3:8b"

    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        timeout: Optional[float] = None,
        stream: bool = False,
        **kwargs
    ) -> ProviderResponse:
        """Send a prompt to the Ollama LLM and return the response.

        Args:
            prompt: The user prompt.
            system: Optional system prompt.
            messages: Optional list of previous messages for conversation context.
            timeout: Optional timeout override for this request.
            stream: Whether to stream the response (not recommended for most use cases).
            **kwargs: Additional parameters passed to the Ollama API.

        Returns:
            ProviderResponse containing the LLM's response text.

        Raises:
            ProviderConnectionError: If unable to connect to the Ollama server.
            ProviderTimeoutError: If the request times out.
            ProviderModelNotFoundError: If the model is not available.
            ProviderError: For other Ollama-specific errors.
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        effective_model = kwargs.pop("model", self.model)

        # Build messages list
        chat_messages = self._build_messages(prompt, system, messages)

        request_start = time.time()

        try:
            logger.info(f"[Ollama] Sending request to {effective_model} (timeout: {effective_timeout}s)")
            logger.debug(f"[Ollama] Request messages: {json.dumps(chat_messages, indent=2)}")

            response = self._client.chat(
                model=effective_model,
                messages=chat_messages,
                stream=stream,
                timeout=effective_timeout,
                **kwargs
            )

            request_duration = time.time() - request_start
            self._last_request_duration = request_duration

            # Extract response content
            if stream:
                # Handle streaming response
                content = self._process_stream_response(response)
            else:
                # Handle non-streaming response
                content = self._extract_content(response)

            response_duration = time.time() - request_start - request_duration
            self._last_response_duration = response_duration

            # Log successful response
            logger.info(
                f"[Ollama] Received response from {effective_model} "
                f"(request: {request_duration:.2f}s, response: {response_duration:.2f}s, "
                f"length: {len(content)} chars)"
            )
            logger.debug(f"[Ollama] Response: {content[:500]}..." if len(content) > 500 else f"[Ollama] Response: {content}")

            return ProviderResponse(
                content=content,
                model=effective_model,
                provider=self.provider_name,
                finish_reason=response.get("done", True),
                raw_response=response,
                request_duration=request_duration,
                response_duration=response_duration,
            )

        except urllib.error.URLError as e:
            error_msg = self._parse_url_error(e, effective_model)
            logger.error(f"[Ollama] Connection error: {error_msg}")
            raise ProviderConnectionError(
                message=error_msg,
                provider_name=self.provider_name,
                details={"model": effective_model, "url": self.base_url, "error": str(e)},
            )
        except TimeoutError as e:
            error_msg = f"Request to Ollama server timed out after {effective_timeout} seconds"
            logger.error(f"[Ollama] Timeout error: {error_msg}")
            raise ProviderTimeoutError(
                message=error_msg,
                provider_name=self.provider_name,
                timeout_seconds=effective_timeout,
                details={"model": effective_model, "error": str(e)},
            )
        except json.JSONDecodeError as e:
            error_msg = f"Invalid response format from Ollama server"
            logger.error(f"[Ollama] JSON decode error: {error_msg} - {str(e)}")
            raise ProviderError(
                message=error_msg,
                provider_name=self.provider_name,
                details={"model": effective_model, "error": str(e)},
            )
        except Exception as e:
            error_msg = str(e) or "Unknown error occurred"
            logger.error(f"[Ollama] Unexpected error: {error_msg}")
            raise ProviderError(
                message=f"Unexpected error: {error_msg}",
                provider_name=self.provider_name,
                details={"model": effective_model, "error": str(e), "type": type(e).__name__},
            )

    def _build_messages(
        self,
        prompt: str,
        system: Optional[str] = None,
        messages: Optional[List[Message]] = None,
    ) -> List[Dict[str, str]]:
        """Build the messages list for the Ollama API.

        Args:
            prompt: The user prompt.
            system: Optional system prompt.
            messages: Optional list of previous messages.

        Returns:
            List of message dictionaries compatible with Ollama API.
        """
        chat_messages: List[Dict[str, str]] = []

        # Add existing messages if provided
        if messages:
            for msg in messages:
                chat_messages.append({"role": msg.role, "content": msg.content})

        # Add system message if provided
        if system:
            chat_messages.append({"role": "system", "content": system})

        # Add user prompt
        chat_messages.append({"role": "user", "content": prompt})

        return chat_messages

    def _extract_content(self, response: Dict[str, Any]) -> str:
        """Extract content from a non-streaming Ollama response.

        Args:
            response: The raw response from Ollama API.

        Returns:
            The extracted content string.

        Raises:
            ProviderError: If the response format is unexpected.
        """
        try:
            # Handle chat endpoint response
            if "message" in response:
                return response["message"].get("content", "")
            # Handle generate endpoint response
            elif "response" in response:
                return response["response"]
            # Handle raw text response
            elif isinstance(response, str):
                return response
            else:
                logger.warning(f"[Ollama] Unexpected response format: {response}")
                return str(response)
        except Exception as e:
            raise ProviderError(
                message=f"Failed to extract content from response",
                provider_name=self.provider_name,
                details={"response": response, "error": str(e)},
            )

    def _process_stream_response(self, response) -> str:
        """Process a streaming response from Ollama.

        Args:
            response: The streaming response iterator.

        Returns:
            The concatenated content string.
        """
        content_parts = []
        for chunk in response:
            if isinstance(chunk, dict):
                if "message" in chunk and "content" in chunk["message"]:
                    content_parts.append(chunk["message"]["content"])
                elif "response" in chunk:
                    content_parts.append(chunk["response"])
            elif isinstance(chunk, str):
                content_parts.append(chunk)
        return "".join(content_parts)

    def _parse_url_error(self, error: urllib.error.URLError, model: str) -> str:
        """Parse a URLError to determine the specific error message.

        Args:
            error: The URLError that occurred.
            model: The model name for context.

        Returns:
            A descriptive error message.
        """
        reason = error.reason

        if isinstance(reason, str):
            reason_lower = reason.lower()
            if "connection refused" in reason_lower:
                return f"Ollama server at {self.base_url} is not running or refused connection"
            elif "name or service not known" in reason_lower or "nodename nor servname provided" in reason_lower:
                return f"Ollama server hostname could not be resolved"
            elif "timeout" in reason_lower:
                return f"Connection to Ollama server at {self.base_url} timed out"
            return f"Connection error: {reason}"

        if isinstance(reason, ConnectionRefusedError):
            return f"Ollama server at {self.base_url} is not running or refused connection"
        if isinstance(reason, ConnectionResetError):
            return f"Connection to Ollama server at {self.base_url} was reset"
        if isinstance(reason, TimeoutError):
            return f"Connection to Ollama server at {self.base_url} timed out"

        return f"Failed to connect to Ollama server at {self.base_url}: {reason}"

    def check_health(self) -> ProviderHealthStatus:
        """Check the health of the Ollama provider.

        Performs connectivity and model availability checks.

        Returns:
            ProviderHealthStatus indicating the current health of the provider.
        """

        is_reachable = False
        model_available = False
        error_message = None
        details: Dict[str, Any] = {}

        try:
            # First, check if the server is reachable
            start_time = time.time()
            response = self._client.get("/api/tags", timeout=5.0)
            details["server_response_time"] = time.time() - start_time

            if response and isinstance(response, dict) and "models" in response:
                is_reachable = True
                available_models = [m["name"] for m in response.get("models", [])]
                details["available_models"] = available_models

                # Check if our configured model is available
                if self.model in available_models:
                    model_available = True
                else:
                    error_message = f"Model '{self.model}' not found. Available: {available_models}"

            else:
                error_message = "Unexpected response format from /api/tags"

        except urllib.error.URLError as e:
            error_message = self._parse_url_error(e, self.model)
        except TimeoutError:
            error_message = f"Ollama server at {self.base_url} did not respond within 5 seconds"
        except Exception as e:
            error_message = f"Health check failed: {str(e)}"

        is_healthy = is_reachable and model_available

        status = ProviderHealthStatus(
            provider_name=self.provider_name,
            is_healthy=is_healthy,
            is_reachable=is_reachable,
            model_available=model_available,
            model_name=self.model,
            error_message=error_message,
            details=details,
        )

        previous_state = self._last_health_state
        if previous_state is None and is_healthy:
            logger.info(f"Ollama available: {self.model}")
        elif previous_state is not None and previous_state != is_healthy:
            if is_healthy:
                logger.info("Ollama connection restored")
            else:
                logger.warning(f"Ollama health check failed: {error_message or 'provider unavailable'}")
        self._last_health_state = is_healthy
        return status

    def list_models(self) -> List[str]:
        """List available models from the Ollama server.

        Returns:
            List of available model names.

        Raises:
            ProviderConnectionError: If unable to connect to the Ollama server.
            ProviderError: For other errors.
        """
        logger.info("[Ollama] Fetching available models")

        try:
            response = self._client.get("/api/tags", timeout=10.0)

            if response and isinstance(response, dict):
                models = [m["name"] for m in response.get("models", [])]
                logger.info(f"[Ollama] Found {len(models)} models: {models}")
                return models

            raise ProviderError(
                message="Unexpected response format from /api/tags",
                provider_name=self.provider_name,
                details={"response": response},
            )

        except urllib.error.URLError as e:
            error_msg = self._parse_url_error(e, "")
            logger.error(f"[Ollama] Failed to list models: {error_msg}")
            raise ProviderConnectionError(
                message=error_msg,
                provider_name=self.provider_name,
                details={"error": str(e)},
            )
        except TimeoutError:
            logger.error("[Ollama] Listing models timed out")
            raise ProviderConnectionError(
                message="Request to list models timed out",
                provider_name=self.provider_name,
            )
        except Exception as e:
            logger.error(f"[Ollama] Failed to list models: {str(e)}")
            raise ProviderError(
                message=f"Failed to list models: {str(e)}",
                provider_name=self.provider_name,
                details={"error": str(e)},
            )

    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model.

        Args:
            model_name: The name of the model to query.

        Returns:
            Dictionary containing model information, or None if not found.
        """
        try:
            models = self.list_models()
            # This is a simplified implementation; could be enhanced with /api/show
            if model_name in models:
                return {"name": model_name, "available": True}
            return None
        except Exception:
            return None


class OllamaClient:
    """Low-level HTTP client for the Ollama API.

    Handles all HTTP communication with the Ollama server.
    """

    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 120.0):
        """Initialize the Ollama client.

        Args:
            base_url: The base URL of the Ollama server.
            timeout: Default timeout for requests in seconds.
        """
        # Use default URL if none provided
        if base_url is None:
            base_url = "http://localhost:11434"
            logger.warning(
                f"[OllamaClient] No base_url provided, using default: {base_url}"
            )
        self.base_url = base_url.rstrip("/")
        self.default_timeout = timeout

    def get(self, endpoint: str, timeout: Optional[float] = None) -> Any:
        """Send a GET request to the Ollama API.

        Args:
            endpoint: The API endpoint (e.g., "/api/tags").
            timeout: Optional timeout override.

        Returns:
            The parsed JSON response.

        Raises:
            urllib.error.URLError: If the request fails.
            TimeoutError: If the request times out.
            json.JSONDecodeError: If the response is not valid JSON.
        """
        url = f"{self.base_url}{endpoint}"
        effective_timeout = timeout if timeout is not None else self.default_timeout

        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except TimeoutError:
            raise
        except urllib.error.URLError:
            raise

    def post(self, endpoint: str, data: Any, timeout: Optional[float] = None) -> Any:
        """Send a POST request to the Ollama API.

        Args:
            endpoint: The API endpoint (e.g., "/api/chat").
            data: The data to send as JSON.
            timeout: Optional timeout override.

        Returns:
            The parsed JSON response.

        Raises:
            urllib.error.URLError: If the request fails.
            TimeoutError: If the request times out.
            json.JSONDecodeError: If the response is not valid JSON.
        """
        url = f"{self.base_url}{endpoint}"
        effective_timeout = timeout if timeout is not None else self.default_timeout

        body = json.dumps(data).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body)
        except TimeoutError:
            raise
        except urllib.error.URLError:
            raise

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """Send a chat request to the Ollama API.

        Args:
            model: The model to use.
            messages: List of chat messages.
            stream: Whether to stream the response.
            timeout: Optional timeout override.
            **kwargs: Additional parameters (options like temperature, etc.).

        Returns:
            The response from the Ollama API.
        """
        endpoint = "/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        # Add optional parameters
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value

        if stream:
            # For streaming, we need special handling
            return self._chat_stream(endpoint, payload, timeout)
        else:
            return self.post(endpoint, payload, timeout)

    def _chat_stream(self, endpoint: str, payload: Dict, timeout: Optional[float] = None) -> List[Dict]:
        """Handle streaming chat response.

        Args:
            endpoint: The API endpoint.
            payload: The request payload.
            timeout: Optional timeout override.

        Returns:
            List of response chunks.
        """
        url = f"{self.base_url}{endpoint}"
        effective_timeout = timeout if timeout is not None else self.default_timeout

        body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        chunks = []
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                for line in response:
                    line = line.decode("utf-8").strip()
                    if line:
                        try:
                            chunk = json.loads(line)
                            chunks.append(chunk)
                        except json.JSONDecodeError:
                            # Skip invalid JSON lines
                            continue
            return chunks
        except TimeoutError:
            raise
        except urllib.error.URLError:
            raise

    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """Send a generate request to the Ollama API (legacy endpoint).

        Args:
            model: The model to use.
            prompt: The prompt to generate from.
            system: Optional system prompt.
            timeout: Optional timeout override.
            **kwargs: Additional parameters.

        Returns:
            The response from the Ollama API.
        """
        endpoint = "/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
        }
        if system:
            payload["system"] = system
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value

        return self.post(endpoint, payload, timeout)
