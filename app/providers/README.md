# LLM Provider Abstraction Layer

This module provides a clean abstraction for different LLM providers, allowing Freya to work with multiple AI services (Ollama, Claude, OpenAI, etc.) through a unified interface.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Freya Application                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                         LLM Class                             │
│  (app/core/llm.py) - Main interface for backward compatibility│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Provider Factory                         │
│  (app/providers/factory.py) - Creates provider instances     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┬───────────────┬───────────────┐
              ▼               ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ 
│  OllamaProvider  │ │ ClaudeProvider  │ │ OpenAIProvider  │ 
│ (app/providers/  │ │  (future)       │ │  (future)       │ 
│  ollama.py)      │ │                 │ │                 │ 
└─────────────────┘ └─────────────────┘ └─────────────────┘ 
              │               │               │
              ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                      BaseLLMProvider                          │
│  (app/providers/base.py) - Abstract base class               │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Using the Default Provider (Ollama)

```python
from app.core.llm import LLM

# Create an LLM instance with default settings
llm = LLM()

# Ask a question
response = llm.ask("What is 2+2?")
print(response)
```

### Specifying a Provider

```python
from app.core.llm import LLM

# Create an LLM instance with explicit provider
llm = LLM(provider="ollama", model="llama3:70b")

# Ask a question
response = llm.ask("What is 2+2?")
```

### Using the Provider Factory Directly

```python
from app.providers.factory import ProviderFactory
from app.providers.base import ProviderConfig

# Create a provider using the factory
provider = ProviderFactory.create(
    provider_name="ollama",
    model="qwen3:8b",
    base_url="http://localhost:11434",
    timeout=120.0,
)

# Use the provider directly
response = provider.ask("Hello, world!", system="You are helpful.")
```

## Configuration

### Environment Variables

The provider system supports both legacy and new configuration via environment variables:

#### Legacy (Backward Compatible)
```bash
MODEL=qwen3:8b
LLM_TIMEOUT=120
```

#### New Multi-Provider Configuration
```bash
# Default provider to use
DEFAULT_PROVIDER=ollama

# Ollama-specific settings
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
OLLAMA_TIMEOUT=120.0

# Claude-specific settings
CLAUDE_API_KEY=your_api_key_here
CLAUDE_MODEL=claude-3-5-sonnet-20250620
CLAUDE_BASE_URL=https://api.anthropic.com
CLAUDE_TIMEOUT=120.0

# OpenAI-specific settings
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com
OPENAI_TIMEOUT=120.0

# Health check settings
HEALTH_CHECK_ON_STARTUP=true
HEALTH_CHECK_TIMEOUT=5.0

# Logging settings
LOG_LEVEL=INFO
LOG_PROVIDER_REQUESTS=true
```

### Configuration File

Create a `.env` file in the project root:

```env
# Project settings
PROJECT_NAME=Freya
WORKSPACE=./

# LLM settings
DEFAULT_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TIMEOUT=120

# Enable health check on startup
HEALTH_CHECK_ON_STARTUP=true
```

## Provider Implementation

### Adding a New Provider

To add a new provider (e.g., for a custom LLM service):

1. Create a new file in `app/providers/` (e.g., `app/providers/my_provider.py`)

2. Implement the provider class:

```python
from app.providers.base import BaseLLMProvider, ProviderConfig, ProviderResponse, Message
from app.core.logger import logger

class MyProvider(BaseLLMProvider):
    provider_name = "my_provider"

    def __init__(self, config: ProviderConfig = None):
        super().__init__(config or ProviderConfig(provider_name="my_provider"))
        # Initialize your provider here
        self.api_key = config.extra.get("api_key")

    def ask(self, prompt: str, system: str = None, messages: list = None, timeout: float = None, **kwargs) -> ProviderResponse:
        # Implement the ask method to call your LLM service
        # Convert messages to your API format
        # Call the API
        # Return ProviderResponse
        pass

    def check_health(self):
        # Check if the provider is reachable and the model is available
        pass

    def list_models(self) -> list:
        # Return list of available models
        pass
```

3. Register the provider in the factory (in `app/providers/factory.py`):

```python
from app.providers.my_provider import MyProvider

# Register the provider
ProviderFactory.register_provider("my_provider", MyProvider)
```

### ProviderFactory Behavior

The `ProviderFactory` is responsible for creating provider instances. It:

1. **Builds Configuration**: Combines explicit parameters, environment variables, and
   defaults to create a complete `ProviderConfig`.

2. **Validates Configuration**: Performs defensive validation to ensure required
   configuration is present. For Ollama providers, if `base_url` is not configured,
   it defaults to `http://localhost:11434`.

3. **Creates Instances**: Instantiates the appropriate provider class with the
   complete configuration.

4. **Manages Registration**: Maintains a registry of available provider classes.

The factory ensures that providers are always created with valid configuration,
preventing `NoneType` errors for required fields like `base_url`.

## Error Handling

The provider layer defines a hierarchy of exceptions:

```
ProviderError
├── ProviderConnectionError      # Connection failures
├── ProviderTimeoutError        # Timeout errors
├── ProviderAuthenticationError # Authentication failures
├── ProviderModelNotFoundError  # Model not available
├── ProviderRateLimitError      # Rate limit exceeded
└── ProviderConfigurationError  # Invalid configuration
```

### Handling Errors

```python
from app.core.llm import LLM, LLMError, LLMConnectionError, LLMTimeoutError

llm = LLM()

try:
    response = llm.ask("Hello")
except LLMTimeoutError as e:
    print(f"Request timed out: {e}")
except LLMConnectionError as e:
    print(f"Connection failed: {e}")
except LLMError as e:
    print(f"General error: {e}")
```

## Health Checks

The provider system includes comprehensive health checking:

```python
from app.core.llm import LLM

# Create an LLM instance
llm = LLM()

# Check if the provider is healthy
if llm.is_healthy():
    print("Provider is healthy!")
else:
    print("Provider is not healthy")

# Get detailed health status
health = llm.check_health()
print(f"Is reachable: {health['is_reachable']}")
print(f"Model available: {health['model_available']}")
print(f"Error: {health.get('error_message')}")
```

### Startup Health Check

The system can automatically verify provider availability on startup:

```python
from app.core.llm import LLM

# This will raise an exception if health check fails
LLM.perform_startup_health_check(
    provider="ollama",
    model="qwen3:8b",
    raise_on_failure=True,
)

# Or with an existing provider instance (avoids creating a duplicate provider)
llm = LLM(provider="ollama", model="qwen3:8b")
LLM.perform_startup_health_check(
    provider="ollama",
    provider_instance=llm._provider,  # Reuse existing provider
    raise_on_failure=True,
)
```

### Startup Sequence

When creating an `LLM` instance, the following happens:

1. **Provider Configuration**: The `LLM.__init__()` method builds a complete `ProviderConfig`
   from the provided parameters, environment variables, and central config.

2. **Provider Creation**: A provider instance is created via `ProviderFactory.create()` with
   the complete configuration (model, base_url, timeout, etc.).

3. **Health Check**: If `HEALTH_CHECK_ON_STARTUP=true` (default), the system performs a
   health check. The health checker **reuses the existing provider instance** instead of
   creating a new one, ensuring that configuration like `base_url` is not lost.

4. **Health Verification**: The provider's `check_health()` method is called to verify:
   - Server is reachable
   - Model is available
   - Connection is working

This approach ensures that only one provider instance is created during startup, and
all configuration values are preserved throughout the health check process.

### Provider Lifecycle

1. **Creation**: Provider instances are created by `ProviderFactory.create()` with a
   complete `ProviderConfig`.

2. **Reuse**: The same provider instance is reused for both normal operations and health
   checks. This prevents duplicate provider creation and configuration loss.

3. **Cleanup**: Provider instances are garbage collected when the `LLM` instance that
   owns them is destroyed.

4. **Reccreation**: If you need a fresh provider instance (e.g., after configuration
   changes), simply create a new `LLM` instance.

### HealthChecker Behavior

The `ProviderHealthChecker` class provides three ways to check provider health:

1. **`check_provider(provider_name, provider=None, **kwargs)`**: Checks a specific provider.
   If `provider` is passed, it reuses that instance. Otherwise, creates a new one.

2. **`verify_startup(provider_name, provider=None, **kwargs)`**: Designed for startup
   verification. Accepts an existing provider instance to reuse.

3. **`check_default_provider(provider=None, **kwargs)`**: Checks the default provider,
   with optional provider reuse.

4. **`check_all_providers()`**: Checks all registered providers. Creates new instances
   for each provider (since it needs to test all of them).

All methods return a `HealthCheckResult` with detailed status information.

## Logging

The provider system logs all operations:

```
[LLM] Initialized with provider=ollama, model=qwen3:8b, timeout=120.0
[LLM] Ask: provider=ollama, model=qwen3:8b
[LLM] Prompt: Hello, world!
[Ollama] Sending request to qwen3:8b (timeout: 120.0s)
[Ollama] Received response from qwen3:8b (request: 1.50s, response: 0.01s, length: 13 chars)
[LLM] Response received in 1.52s (provider=ollama, model=qwen3:8b)
```

## Best Practices

1. **Always handle exceptions**: Wrap LLM calls in try-except blocks to handle network and provider errors gracefully.

2. **Use appropriate timeouts**: Set reasonable timeouts based on the expected response time of your model.

3. **Specify models explicitly**: While defaults are provided, explicitly specifying models makes your code more maintainable.

4. **Check health on startup**: Use `LLM.perform_startup_health_check()` to verify provider availability before starting operations.

5. **Use streaming for long responses**: For long responses, consider using the streaming option if your provider supports it.

## Migration Guide

### From Legacy LLM Class

The new provider layer is designed to be backward compatible with the existing LLM class.

**Before:**
```python
from app.core.llm import LLM

llm = LLM(model="qwen3:8b")
response = llm.ask("Hello")
```

**After:**
```python
from app.core.llm import LLM

# This still works exactly the same way
llm = LLM(model="qwen3:8b")
response = llm.ask("Hello")

# Or with explicit provider
llm = LLM(provider="ollama", model="qwen3:8b")
response = llm.ask("Hello")
```

### From Direct Ollama Calls

**Before:**
```python
import ollama

response = ollama.chat(
    model="qwen2.5-coder:14b",
    messages=[
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
    ],
)
```

**After:**
```python
from app.core.llm import LLM

llm = LLM(provider="ollama", model="qwen3:8b")
response = llm.ask("Hello", system="You are helpful")
```

## Supported Providers

| Provider | Status | Default Model | Configuration |
|----------|--------|--------------|---------------|
| Ollama | ✅ Implemented | qwen3:8b | OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT |
| Claude | 🔲 Planned | claude-3-5-sonnet-20250620 | CLAUDE_API_KEY, CLAUDE_MODEL, CLAUDE_BASE_URL |
| OpenAI | 🔲 Planned | gpt-4o-mini | OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL |
| Gemini | 🔲 Planned | gemini-1.5-flash | GEMINI_API_KEY, GEMINI_MODEL, GEMINI_BASE_URL |
| DeepSeek | 🔲 Planned | deepseek-chat | DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL |

## Troubleshooting

### "Provider not found" error

If you get a "Provider not found" error, ensure the provider is registered:

```python
from app.providers.factory import ProviderFactory

# Check registered providers
print(ProviderFactory.get_registered_providers())
```

### "Model not found" error

Ensure the model exists on your provider. For Ollama:

```bash
# List available models
ollama list

# Pull a model
ollama pull qwen3:8b
```

### "Connection refused" error

Ensure the provider server is running. For Ollama:

```bash
# Start the Ollama server
ollama serve

# Or run a model directly
ollama run qwen3:8b
```

### Timeout errors

Increase the timeout value:

```python
llm = LLM(timeout=300)  # 5 minutes
```

Or in the environment:

```bash
export LLM_TIMEOUT=300
```
