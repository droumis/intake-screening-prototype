"""OllamaProvider — local model access via Ollama HTTP API."""

from __future__ import annotations

import json
import logging

import httpx
import jsonschema

from pisa.config import ModelConfig
from pisa.model.provider import ProviderStatus

logger = logging.getLogger(__name__)


class OllamaProvider:
    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")

    @property
    def context_limit(self) -> int:
        return self._config.num_ctx

    def health_check(self) -> ProviderStatus:
        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=5.0)
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            return ProviderStatus(
                available=False,
                server_reachable=False,
                model_loaded=False,
                model_name=self._config.model,
                message=f"Cannot reach Ollama server at {self._base_url}: {e}",
            )

        models = resp.json().get("models", [])
        model_names = [m.get("name", "") for m in models]
        # Match with or without :latest suffix
        target = self._config.model
        model_found = any(
            name == target or name == f"{target}:latest" or name.startswith(f"{target}:")
            for name in model_names
        )

        if not model_found:
            return ProviderStatus(
                available=False,
                server_reachable=True,
                model_loaded=False,
                model_name=target,
                message=f"Model '{target}' not found. Run: ollama pull {target}",
            )

        return ProviderStatus(
            available=True,
            server_reachable=True,
            model_loaded=True,
            model_name=target,
            message="Ready",
        )

    def analyze(
        self,
        prompt: str,
        response_schema: dict,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> dict:
        """Send a prompt to the model with structured output and return validated JSON."""
        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "format": response_schema,
            "options": {
                "temperature": temperature if temperature is not None else self._config.temperature,
                "num_ctx": self._config.num_ctx,
                "num_predict": max_tokens,
            },
        }

        for attempt in range(1 + self._config.max_retries):
            try:
                resp = httpx.post(
                    f"{self._base_url}/api/generate",
                    json=payload,
                    timeout=600.0,
                )
                resp.raise_for_status()
            except httpx.ConnectError as e:
                raise ModelResponseError(
                    f"Cannot connect to Ollama at {self._base_url}. Is it running?"
                ) from e
            except httpx.TimeoutException as e:
                raise ModelResponseError(
                    f"Ollama request timed out after 600s. The prompt may be too large "
                    f"or the model too slow for this hardware."
                ) from e
            except httpx.HTTPStatusError as e:
                raise ModelResponseError(
                    f"Ollama returned HTTP {e.response.status_code}: {e.response.text[:200]}"
                ) from e

            resp_json = resp.json()
            # qwen3 models in thinking mode put structured output in "thinking"
            # when "response" is empty; check both fields.
            raw_response = resp_json.get("response", "") or resp_json.get("thinking", "")
            try:
                parsed = json.loads(raw_response)
            except json.JSONDecodeError as e:
                if attempt < self._config.max_retries:
                    payload["prompt"] = (
                        f"{prompt}\n\n[RETRY: Your previous response was not valid JSON. "
                        f"Error: {e}. Please respond with valid JSON only.]"
                    )
                    continue
                raise ModelResponseError(f"Model returned invalid JSON after retries: {e}") from e

            try:
                jsonschema.validate(parsed, response_schema)
            except jsonschema.ValidationError as e:
                if attempt < self._config.max_retries:
                    payload["prompt"] = (
                        f"{prompt}\n\n[RETRY: Your previous response did not match the required schema. "
                        f"Validation error: {e.message}. Please correct and respond again.]"
                    )
                    continue
                raise ModelResponseError(
                    f"Model response failed schema validation after retries: {e.message}"
                ) from e

            return parsed

        raise ModelResponseError("Exhausted retries without a valid response")


class ModelResponseError(Exception):
    """Raised when the model fails to produce a valid, schema-conforming response."""
