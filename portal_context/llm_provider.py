"""
LLM Provider abstraction for Portal Context Generator.

Supports three backends:
- GeminiProvider: Google Gemini API (free tier)
- OpenAICompatibleProvider: Any OpenAI-compatible endpoint via httpx
- CustomAPIProvider: Any simple POST API with configurable field mapping
"""

import base64
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Send a prompt and get a text response."""
        ...

    @abstractmethod
    async def generate_with_image(self, prompt: str, image_path: str, system_prompt: str = "") -> str:
        """Send a prompt with an image and get a text response."""
        ...

    async def close(self):
        """Cleanup resources if needed."""
        pass


class GeminiProvider(LLMProvider):
    """
    Google Gemini API provider using google-genai SDK.
    
    Free tier supports:
    - gemini-2.0-flash: 15 RPM, 1M TPM
    - gemini-2.5-flash: 10 RPM, 250K TPM
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy-initialize the Gemini client."""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "google-genai package is required for Gemini provider. "
                    "Install it with: pip install google-genai"
                )
        return self._client

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate text using Gemini API."""
        client = self._get_client()
        
        contents = []
        if system_prompt:
            contents.append(f"System Instructions: {system_prompt}\n\n")
        contents.append(prompt)
        
        full_prompt = "".join(contents)
        
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=full_prompt,
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    async def generate_with_image(self, prompt: str, image_path: str, system_prompt: str = "") -> str:
        """Generate text with an image using Gemini API (multimodal)."""
        client = self._get_client()
        
        image_data = Path(image_path).read_bytes()
        
        # Determine MIME type
        suffix = Path(image_path).suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime_type = mime_map.get(suffix, "image/png")
        
        from google.genai import types
        
        contents = []
        if system_prompt:
            contents.append(f"System Instructions: {system_prompt}\n\n")
        contents.append(prompt)
        contents.append(types.Part.from_bytes(data=image_data, mime_type=mime_type))
        
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error (multimodal): {e}")
            raise


class OpenAICompatibleProvider(LLMProvider):
    """
    OpenAI-compatible API provider using plain httpx.
    
    Works with any server that exposes POST /v1/chat/completions
    (vLLM, Ollama, LM Studio, text-generation-webui, etc.)
    """

    def __init__(self, base_url: str, api_key: str = "", model: str = "default"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the httpx client."""
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate text via OpenAI-compatible chat completions endpoint."""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4000,
        }

        url = f"{self.base_url}/chat/completions"
        if "/v1" not in self.base_url:
            url = f"{self.base_url}/v1/chat/completions"

        try:
            response = await client.post(url, json=body)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenAI-compatible API HTTP error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"OpenAI-compatible API error: {e}")
            raise

    async def generate_with_image(self, prompt: str, image_path: str, system_prompt: str = "") -> str:
        """Generate text with an image via OpenAI-compatible vision endpoint."""
        client = self._get_client()

        # Encode image as base64
        image_data = Path(image_path).read_bytes()
        b64_image = base64.b64encode(image_data).decode("utf-8")

        suffix = Path(image_path).suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime_type = mime_map.get(suffix, "image/png")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_image}"}
                }
            ]
        })

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4000,
        }

        url = f"{self.base_url}/chat/completions"
        if "/v1" not in self.base_url:
            url = f"{self.base_url}/v1/chat/completions"

        try:
            response = await client.post(url, json=body)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI-compatible API error (vision): {e}")
            raise

    async def close(self):
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class CustomAPIProvider(LLMProvider):
    """
    Custom API provider for non-standard LLM endpoints.
    
    Supports any simple POST endpoint with configurable
    request/response field mapping.
    
    Example:
        POST http://your-llm:5000/generate
        Body: {"input": "prompt text..."}
        Response: {"output": "generated text..."}
    """

    def __init__(
        self,
        base_url: str,
        request_field: str = "input",
        response_field: str = "output",
        api_key: str = "",
        extra_params: dict = None,
    ):
        self.base_url = base_url
        self.request_field = request_field
        self.response_field = response_field
        self.api_key = api_key
        self.extra_params = extra_params or {}
        self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the httpx client."""
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate text via custom POST endpoint."""
        client = self._get_client()

        # Combine system prompt and user prompt
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        # Build request body
        body = {self.request_field: full_prompt}
        body.update(self.extra_params)

        try:
            response = await client.post(self.base_url, json=body)
            response.raise_for_status()
            result = response.json()

            # Navigate nested response fields (supports "data.result.text" style)
            output = result
            for key in self.response_field.split("."):
                output = output[key]

            return str(output)
        except httpx.HTTPStatusError as e:
            logger.error(f"Custom LLM API HTTP error: {e.response.status_code} - {e.response.text}")
            raise
        except KeyError as e:
            logger.error(
                f"Custom LLM API response missing field '{self.response_field}'. "
                f"Available keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}"
            )
            raise
        except Exception as e:
            logger.error(f"Custom LLM API error: {e}")
            raise

    async def generate_with_image(self, prompt: str, image_path: str, system_prompt: str = "") -> str:
        """
        Image support for custom APIs.
        
        Falls back to text-only generation since custom APIs
        typically don't support multimodal input.
        """
        logger.warning(
            "Custom API provider does not support image input. "
            "Falling back to text-only generation."
        )
        return await self.generate(prompt, system_prompt)

    async def close(self):
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None


def create_provider(config) -> LLMProvider:
    """
    Factory function to create the appropriate LLM provider from config.
    
    Args:
        config: PortalConfig instance
        
    Returns:
        LLMProvider instance
    """
    if config.llm_provider == "gemini":
        return GeminiProvider(
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    elif config.llm_provider == "openai":
        return OpenAICompatibleProvider(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    elif config.llm_provider == "custom":
        return CustomAPIProvider(
            base_url=config.llm_base_url,
            request_field=config.llm_request_field,
            response_field=config.llm_response_field,
            api_key=config.llm_api_key,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {config.llm_provider}")
