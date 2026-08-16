"""Application configuration loaded from config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class ModelConfig:
    provider: str = "ollama"
    model: str = "qwen3:30b-a3b"
    temperature: float = 0.1
    num_ctx: int = 16384
    max_retries: int = 1
    base_url: str = "http://localhost:11434"


@dataclass(frozen=True)
class AppConfig:
    data_dir: str = "demo-data"
    db_path: str = "pisa.db"


@dataclass(frozen=True)
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    app: AppConfig = field(default_factory=AppConfig)


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    model_raw = raw.get("model", {})
    app_raw = raw.get("app", {})

    return Config(
        model=ModelConfig(**{k: v for k, v in model_raw.items() if k in ModelConfig.__dataclass_fields__}),
        app=AppConfig(**{k: v for k, v in app_raw.items() if k in AppConfig.__dataclass_fields__}),
    )
