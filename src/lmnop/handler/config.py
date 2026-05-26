from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

import yaml
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
DEFAULT_CORS_ALLOW_ORIGIN_REGEX = r"^https://[A-Za-z0-9-]+\.share\.zrok\.io$"
DEFAULT_CONFIG_DIRNAME = "lmnop-handler"
DEFAULT_CONFIG_FILENAME = "config.yaml"
ENV_CONFIG = "LMNOP_HANDLER_CONFIG"
ENV_HOST = "LMNOP_HANDLER_HOST"
ENV_PORT = "LMNOP_HANDLER_PORT"
ENV_OBSIDIAN_BIN = "LMNOP_HANDLER_OBSIDIAN_BIN"
ENV_VAULT_ROOT = "LMNOP_HANDLER_VAULT_ROOT"
ENV_VAULT_SELECTOR = "LMNOP_HANDLER_VAULT_SELECTOR"
ENV_BEARER_TOKENS = "LMNOP_HANDLER_BEARER_TOKENS"
ENV_CORS_ALLOW_ORIGIN_REGEX = "LMNOP_HANDLER_CORS_ALLOW_ORIGIN_REGEX"
ENV_RECENT_DAILY_NOTE_COUNT = "LMNOP_HANDLER_RECENT_DAILY_NOTE_COUNT"
ENV_UPCOMING_DAYS = "LMNOP_HANDLER_UPCOMING_DAYS"
ENV_LAUNCH_DETECTION_TIMEOUT = "LMNOP_HANDLER_LAUNCH_DETECTION_TIMEOUT"
ENV_READINESS_TIMEOUT = "LMNOP_HANDLER_READINESS_TIMEOUT"
ENV_READINESS_POLL_INTERVAL = "LMNOP_HANDLER_READINESS_POLL_INTERVAL"
ENV_COMMAND_TIMEOUT = "LMNOP_HANDLER_COMMAND_TIMEOUT"
ENV_XDG_CONFIG_HOME = "XDG_CONFIG_HOME"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedSettings:
    settings: Settings
    config_path: Path
    env_overrides: tuple[str, ...]


class Settings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    host: str = DEFAULT_HOST
    port: int = Field(default=DEFAULT_PORT, ge=1)
    obsidian_bin: str = DEFAULT_OBSIDIAN_BIN
    vault_root: Path
    bearer_tokens: dict[str, str] = Field(default_factory=dict)
    cors_allow_origin_regex: str | None = DEFAULT_CORS_ALLOW_ORIGIN_REGEX
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
        for client_id, token in value.items():
            if not client_id:
                raise ValueError("Bearer token client IDs must be non-empty")
            if not token:
                raise ValueError("Bearer tokens must be non-empty")
        return value

    @field_validator("cors_allow_origin_regex")
    @classmethod
    def validate_cors_allow_origin_regex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            _ = re.compile(value)
        except re.error as exc:
            raise ValueError(f"Invalid CORS origin regex: {value}") from exc
        return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    return load_loaded_settings(env).settings


def load_loaded_settings(env: Mapping[str, str] | None = None) -> LoadedSettings:
    values = env if env is not None else os.environ
    config_path = _resolve_config_path(values)
    payload = _load_config_payload(config_path)
    merged_payload, env_overrides = _apply_environment_overrides(payload, values)

    try:
        settings = Settings.model_validate(merged_payload)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc

    return LoadedSettings(
        settings=settings,
        config_path=config_path,
        env_overrides=env_overrides,
    )


def format_settings_report(loaded: LoadedSettings) -> str:
    settings = loaded.settings
    overrides = ", ".join(loaded.env_overrides) if loaded.env_overrides else "none"
    lines = [
        "Starting lmnop-handler with configuration",
        f"  Config file: {loaded.config_path}",
        f"  Environment overrides: {overrides}",
        "",
        "  Server",
        f"    Host: {settings.host}",
        f"    Port: {settings.port}",
        f"    CORS origin regex: {settings.cors_allow_origin_regex or '(disabled)'}",
        "",
        "  Obsidian",
        f"    Vault root: {settings.vault_root}",
        f"    Vault selector: {settings.vault_selector or '(none)'}",
        f"    Obsidian binary: {settings.obsidian_bin}",
        "",
        "  Planning",
        f"    Recent daily note count: {settings.recent_daily_note_count}",
        f"    Upcoming days: {settings.upcoming_days}",
        "",
        "  Timeouts",
        f"    Launch detection: {settings.launch_detection_timeout}s",
        f"    Readiness: {settings.readiness_timeout}s",
        f"    Readiness poll interval: {settings.readiness_poll_interval}s",
        f"    Command: {settings.command_timeout}s",
        "",
        "  Authentication",
        "    Disabled: bearer token settings are currently ignored",
    ]
    return "\n".join(lines)


def _resolve_config_path(values: Mapping[str, str]) -> Path:
    raw_config_path = values.get(ENV_CONFIG)
    if raw_config_path is not None:
        stripped = raw_config_path.strip()
        if not stripped:
            raise ConfigError(f"{ENV_CONFIG} must be a non-empty path")
        return Path(stripped).expanduser().resolve()

    raw_xdg_config_home = values.get(ENV_XDG_CONFIG_HOME)
    config_home = (
        Path(raw_xdg_config_home).expanduser()
        if raw_xdg_config_home
        else Path.home() / ".config"
    )
    return (config_home / DEFAULT_CONFIG_DIRNAME / DEFAULT_CONFIG_FILENAME).resolve()


def _load_config_payload(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    if not config_path.is_file():
        raise ConfigError(f"Config path is not a file: {config_path}")

    try:
        parsed = cast(object, yaml.safe_load(config_path.read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {config_path}") from exc

    if not isinstance(parsed, Mapping):
        raise ConfigError("Config file must contain a mapping at the top level")

    parsed_mapping = cast(Mapping[object, object], parsed)
    payload: dict[str, object] = {}
    for key, value in parsed_mapping.items():
        if not isinstance(key, str):
            raise ConfigError("Config file keys must be strings")
        payload[key] = value
    return payload


def _apply_environment_overrides(
    payload: Mapping[str, object], values: Mapping[str, str]
) -> tuple[dict[str, object], tuple[str, ...]]:
    merged = dict(payload)
    overrides: list[str] = []

    if ENV_HOST in values:
        merged["host"] = values[ENV_HOST]
        overrides.append(ENV_HOST)
    if ENV_PORT in values:
        merged["port"] = values[ENV_PORT]
        overrides.append(ENV_PORT)
    if ENV_OBSIDIAN_BIN in values:
        merged["obsidian_bin"] = values[ENV_OBSIDIAN_BIN]
        overrides.append(ENV_OBSIDIAN_BIN)
    if ENV_VAULT_ROOT in values:
        merged["vault_root"] = values[ENV_VAULT_ROOT]
        overrides.append(ENV_VAULT_ROOT)
    if ENV_VAULT_SELECTOR in values:
        merged["vault_selector"] = values[ENV_VAULT_SELECTOR] or None
        overrides.append(ENV_VAULT_SELECTOR)
    if ENV_BEARER_TOKENS in values:
        merged["bearer_tokens"] = _parse_bearer_tokens(values[ENV_BEARER_TOKENS])
        overrides.append(ENV_BEARER_TOKENS)
    if ENV_CORS_ALLOW_ORIGIN_REGEX in values:
        merged["cors_allow_origin_regex"] = values[ENV_CORS_ALLOW_ORIGIN_REGEX] or None
        overrides.append(ENV_CORS_ALLOW_ORIGIN_REGEX)
    if ENV_RECENT_DAILY_NOTE_COUNT in values:
        merged["recent_daily_note_count"] = values[ENV_RECENT_DAILY_NOTE_COUNT]
        overrides.append(ENV_RECENT_DAILY_NOTE_COUNT)
    if ENV_UPCOMING_DAYS in values:
        merged["upcoming_days"] = values[ENV_UPCOMING_DAYS]
        overrides.append(ENV_UPCOMING_DAYS)
    if ENV_LAUNCH_DETECTION_TIMEOUT in values:
        merged["launch_detection_timeout"] = values[ENV_LAUNCH_DETECTION_TIMEOUT]
        overrides.append(ENV_LAUNCH_DETECTION_TIMEOUT)
    if ENV_READINESS_TIMEOUT in values:
        merged["readiness_timeout"] = values[ENV_READINESS_TIMEOUT]
        overrides.append(ENV_READINESS_TIMEOUT)
    if ENV_READINESS_POLL_INTERVAL in values:
        merged["readiness_poll_interval"] = values[ENV_READINESS_POLL_INTERVAL]
        overrides.append(ENV_READINESS_POLL_INTERVAL)
    if ENV_COMMAND_TIMEOUT in values:
        merged["command_timeout"] = values[ENV_COMMAND_TIMEOUT]
        overrides.append(ENV_COMMAND_TIMEOUT)

    return merged, tuple(overrides)


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
