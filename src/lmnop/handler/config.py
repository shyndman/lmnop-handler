from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_OBSIDIAN_BIN = "obsidian"
DEFAULT_RECENT_DAILY_NOTE_COUNT = 2
DEFAULT_UPCOMING_DAYS = 7
DEFAULT_LAUNCH_DETECTION_TIMEOUT = 0.5
DEFAULT_READINESS_TIMEOUT = 15.0
DEFAULT_READINESS_POLL_INTERVAL = 0.25
DEFAULT_COMMAND_TIMEOUT = 15.0

ENV_HOST = "LMNOP_HANDLER_HOST"
ENV_PORT = "LMNOP_HANDLER_PORT"
ENV_OBSIDIAN_BIN = "LMNOP_HANDLER_OBSIDIAN_BIN"
ENV_VAULT_ROOT = "LMNOP_HANDLER_VAULT_ROOT"
ENV_VAULT_SELECTOR = "LMNOP_HANDLER_VAULT_SELECTOR"
ENV_BEARER_TOKENS = "LMNOP_HANDLER_BEARER_TOKENS"
ENV_RECENT_DAILY_NOTE_COUNT = "LMNOP_HANDLER_RECENT_DAILY_NOTE_COUNT"
ENV_UPCOMING_DAYS = "LMNOP_HANDLER_UPCOMING_DAYS"
ENV_LAUNCH_DETECTION_TIMEOUT = "LMNOP_HANDLER_LAUNCH_DETECTION_TIMEOUT"
ENV_READINESS_TIMEOUT = "LMNOP_HANDLER_READINESS_TIMEOUT"
ENV_READINESS_POLL_INTERVAL = "LMNOP_HANDLER_READINESS_POLL_INTERVAL"
ENV_COMMAND_TIMEOUT = "LMNOP_HANDLER_COMMAND_TIMEOUT"


class ConfigError(ValueError):
    pass


class Settings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    host: str = DEFAULT_HOST
    port: int = Field(default=DEFAULT_PORT, ge=1)
    obsidian_bin: str = DEFAULT_OBSIDIAN_BIN
    vault_root: Path
    bearer_tokens: dict[str, str]
    vault_selector: str | None = None
    recent_daily_note_count: int = Field(default=DEFAULT_RECENT_DAILY_NOTE_COUNT, ge=1)
    upcoming_days: int = Field(default=DEFAULT_UPCOMING_DAYS, ge=0)
    launch_detection_timeout: float = Field(
        default=DEFAULT_LAUNCH_DETECTION_TIMEOUT, ge=0.01
    )
    readiness_timeout: float = Field(default=DEFAULT_READINESS_TIMEOUT, ge=0.1)
    readiness_poll_interval: float = Field(
        default=DEFAULT_READINESS_POLL_INTERVAL, ge=0.01
    )
    command_timeout: float = Field(default=DEFAULT_COMMAND_TIMEOUT, ge=0.1)

    @field_validator("vault_root")
    @classmethod
    def validate_vault_root(cls, value: Path) -> Path:
        resolved = value.expanduser().resolve()
        if not resolved.exists():
            raise ValueError(f"Vault root does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Vault root is not a directory: {resolved}")
        return resolved

    @field_validator("bearer_tokens")
    @classmethod
    def validate_bearer_tokens(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("At least one bearer token is required")
        for client_id, token in value.items():
            if not client_id:
                raise ValueError("Bearer token client IDs must be non-empty")
            if not token:
                raise ValueError("Bearer tokens must be non-empty")
        return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    values = env if env is not None else os.environ
    raw_vault_root = values.get(ENV_VAULT_ROOT)
    if not raw_vault_root:
        raise ConfigError(f"Missing required environment variable: {ENV_VAULT_ROOT}")

    raw_tokens = values.get(ENV_BEARER_TOKENS)
    if not raw_tokens:
        raise ConfigError(f"Missing required environment variable: {ENV_BEARER_TOKENS}")

    bearer_tokens = _parse_bearer_tokens(raw_tokens)
    payload: dict[str, object] = {
        "host": values.get(ENV_HOST, DEFAULT_HOST),
        "port": values.get(ENV_PORT, DEFAULT_PORT),
        "obsidian_bin": values.get(ENV_OBSIDIAN_BIN, DEFAULT_OBSIDIAN_BIN),
        "vault_root": raw_vault_root,
        "vault_selector": values.get(ENV_VAULT_SELECTOR) or None,
        "bearer_tokens": bearer_tokens,
        "recent_daily_note_count": values.get(
            ENV_RECENT_DAILY_NOTE_COUNT, DEFAULT_RECENT_DAILY_NOTE_COUNT
        ),
        "upcoming_days": values.get(ENV_UPCOMING_DAYS, DEFAULT_UPCOMING_DAYS),
        "launch_detection_timeout": values.get(
            ENV_LAUNCH_DETECTION_TIMEOUT,
            DEFAULT_LAUNCH_DETECTION_TIMEOUT,
        ),
        "readiness_timeout": values.get(
            ENV_READINESS_TIMEOUT, DEFAULT_READINESS_TIMEOUT
        ),
        "readiness_poll_interval": values.get(
            ENV_READINESS_POLL_INTERVAL,
            DEFAULT_READINESS_POLL_INTERVAL,
        ),
        "command_timeout": values.get(ENV_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT),
    }

    try:
        return Settings.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def _parse_bearer_tokens(raw_tokens: str) -> dict[str, str]:
    try:
        decoded = TypeAdapter(dict[str, str]).validate_json(raw_tokens)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{ENV_BEARER_TOKENS} must be valid JSON") from exc
    for raw_client_id, raw_token in decoded.items():
        if not raw_client_id:
            raise ConfigError(f"{ENV_BEARER_TOKENS} keys must be non-empty strings")
        if not raw_token:
            raise ConfigError(f"{ENV_BEARER_TOKENS} values must be non-empty strings")
    return decoded
