from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

import lmnop.handler as handler_module
from lmnop.handler.application import EnvironmentApplication
from lmnop.handler.config import ConfigError, load_settings


def test_load_settings_requires_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Config file not found"):
        _ = load_settings({"XDG_CONFIG_HOME": str(tmp_path)})


def test_load_settings_reads_yaml_config(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    config_path = _write_config(
        tmp_path,
        vault_root,
        bearer_token="secret-token",
        extra_lines=["host: 127.0.0.1", "port: 8123"],
    )

    settings = load_settings({"LMNOP_HANDLER_CONFIG": str(config_path)})

    assert settings.host == "127.0.0.1"
    assert settings.port == 8123
    assert settings.vault_root == vault_root.resolve()
    assert settings.bearer_tokens == {"claude": "secret-token"}
    assert settings.cors_allow_origin_regex == (
        r"^https://[A-Za-z0-9-]+\.share\.zrok\.io$"
    )


def test_load_settings_allows_missing_bearer_tokens(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    config_path = _write_config(tmp_path, vault_root, extra_lines=["port: 8123"])

    settings = load_settings({"LMNOP_HANDLER_CONFIG": str(config_path)})

    assert settings.port == 8123
    assert settings.bearer_tokens == {}


def test_load_settings_env_overrides_yaml(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    config_path = _write_config(
        tmp_path,
        vault_root,
        bearer_token="from-file-token",
        extra_lines=["host: 127.0.0.1", "port: 8123"],
    )

    settings = load_settings(
        {
            "LMNOP_HANDLER_CONFIG": str(config_path),
            "LMNOP_HANDLER_HOST": "0.0.0.0",
            "LMNOP_HANDLER_PORT": "9000",
            "LMNOP_HANDLER_BEARER_TOKENS": '{"claude":"override-token"}',
            "LMNOP_HANDLER_CORS_ALLOW_ORIGIN_REGEX": r"^https://debug\.example$",
        }
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.bearer_tokens == {"claude": "override-token"}
    assert settings.cors_allow_origin_regex == r"^https://debug\.example$"


def test_load_settings_rejects_invalid_cors_regex(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    config_path = _write_config(
        tmp_path,
        vault_root,
        extra_lines=["cors_allow_origin_regex: '['"],
    )

    with pytest.raises(ConfigError, match="Invalid CORS origin regex"):
        _ = load_settings({"LMNOP_HANDLER_CONFIG": str(config_path)})


def test_load_settings_rejects_invalid_yaml_root(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _ = config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="top level"):
        _ = load_settings({"LMNOP_HANDLER_CONFIG": str(config_path)})


def test_load_settings_rejects_extra_fields(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    config_path = _write_config(
        tmp_path,
        vault_root,
        bearer_token="secret-token",
        extra_lines=["unexpected: nope"],
    )

    with pytest.raises(ConfigError, match="unexpected"):
        _ = load_settings({"LMNOP_HANDLER_CONFIG": str(config_path)})


def test_main_prints_pretty_redacted_startup_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault_root = tmp_path / "vault"
    config_path = _write_config(tmp_path, vault_root, bearer_token="secret-token")
    runtime = EnvironmentApplication({"LMNOP_HANDLER_CONFIG": str(config_path)})
    stub_mcp = _StubMcp()

    def build_mcp(_: object) -> _StubMcp:
        return stub_mcp

    monkeypatch.setattr(handler_module, "DEFAULT_RUNTIME", runtime)
    monkeypatch.setattr(handler_module, "create_mcp", build_mcp)

    handler_module.main()

    captured = capsys.readouterr()
    assert "Starting lmnop-handler with configuration" in captured.out
    assert "Config file:" in captured.out
    assert "Vault root:" in captured.out
    assert "CORS origin regex:" in captured.out
    assert "Authentication" in captured.out
    assert "Disabled: bearer token settings are currently ignored" in captured.out
    assert "secret-token" not in captured.out
    assert stub_mcp.run_kwargs is not None
    assert stub_mcp.run_kwargs["transport"] == "http"
    assert stub_mcp.run_kwargs["host"] == runtime.settings().host
    assert stub_mcp.run_kwargs["port"] == runtime.settings().port
    middleware = cast(list[Middleware], stub_mcp.run_kwargs["middleware"])
    assert len(middleware) == 1
    assert middleware[0].cls is CORSMiddleware
    assert middleware[0].kwargs["allow_origin_regex"] == (
        runtime.settings().cors_allow_origin_regex
    )


def test_main_swallows_sigint_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault_root = tmp_path / "vault"
    config_path = _write_config(tmp_path, vault_root, bearer_token="secret-token")
    runtime = EnvironmentApplication({"LMNOP_HANDLER_CONFIG": str(config_path)})
    stub_mcp = _StubMcp(raise_keyboard_interrupt=True)

    def build_mcp(_: object) -> _StubMcp:
        return stub_mcp

    monkeypatch.setattr(handler_module, "DEFAULT_RUNTIME", runtime)
    monkeypatch.setattr(handler_module, "create_mcp", build_mcp)

    handler_module.main()

    captured = capsys.readouterr()
    assert "Starting lmnop-handler with configuration" in captured.out
    assert captured.err == ""
    assert stub_mcp.run_kwargs is not None
    assert stub_mcp.run_kwargs["transport"] == "http"
    assert stub_mcp.run_kwargs["host"] == runtime.settings().host
    assert stub_mcp.run_kwargs["port"] == runtime.settings().port
    middleware = cast(list[Middleware], stub_mcp.run_kwargs["middleware"])
    assert len(middleware) == 1
    assert middleware[0].cls is CORSMiddleware


class _StubMcp:
    run_kwargs: dict[str, object] | None
    _raise_keyboard_interrupt: bool

    def __init__(self, *, raise_keyboard_interrupt: bool = False) -> None:
        self.run_kwargs = None
        self._raise_keyboard_interrupt = raise_keyboard_interrupt

    def run(
        self,
        *,
        transport: str,
        host: str,
        port: int,
        middleware: list[object] | None = None,
    ) -> None:
        self.run_kwargs = {
            "transport": transport,
            "host": host,
            "port": port,
            "middleware": middleware,
        }
        if self._raise_keyboard_interrupt:
            raise KeyboardInterrupt


def _write_config(
    tmp_path: Path,
    vault_root: Path,
    *,
    bearer_token: str | None = None,
    extra_lines: list[str] | None = None,
) -> Path:
    vault_root.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [f"vault_root: {vault_root}"]
    if bearer_token is not None:
        lines.extend(["bearer_tokens:", f"  claude: {bearer_token}"])
    if extra_lines is not None:
        lines.extend(extra_lines)
    _ = config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path
