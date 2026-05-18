from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import lmnop.handler as handler_module
from lmnop.handler.auth import ConfiguredTokenVerifier
from lmnop.handler.config import ConfigError, load_settings
from lmnop.handler.server import EnvironmentApplication


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
        }
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.bearer_tokens == {"claude": "override-token"}


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
    assert "Bearer tokens" in captured.out
    assert "sec…[redacted]" in captured.out
    assert "secret-token" not in captured.out
    assert stub_mcp.run_kwargs == {
        "transport": "http",
        "host": runtime.settings().host,
        "port": runtime.settings().port,
    }


def test_configured_token_verifier_accepts_valid_token() -> None:
    verifier = ConfiguredTokenVerifier(lambda: {"client": "secret"})

    async def run() -> None:
        assert await verifier.verify_token("wrong") is None
        token = await verifier.verify_token("secret")
        assert token is not None
        assert token.client_id == "client"

    asyncio.run(run())


class _StubMcp:
    run_kwargs: dict[str, object] | None

    def __init__(self) -> None:
        self.run_kwargs = None

    def run(self, *, transport: str, host: str, port: int) -> None:
        self.run_kwargs = {"transport": transport, "host": host, "port": port}


def _write_config(
    tmp_path: Path,
    vault_root: Path,
    *,
    bearer_token: str,
    extra_lines: list[str] | None = None,
) -> Path:
    vault_root.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [
        f"vault_root: {vault_root}",
        "bearer_tokens:",
        f"  claude: {bearer_token}",
    ]
    if extra_lines is not None:
        lines.extend(extra_lines)
    _ = config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path
