"""ModelProvider protocol and status types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProviderStatus:
    available: bool
    server_reachable: bool
    model_loaded: bool
    model_name: str
    message: str


class ModelProvider(Protocol):
    def analyze(self, prompt: str, response_schema: dict, max_tokens: int = 4096) -> dict: ...
    def health_check(self) -> ProviderStatus: ...

    @property
    def context_limit(self) -> int: ...
