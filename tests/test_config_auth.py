from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lmnop.handler.auth import ConfiguredTokenVerifier
from lmnop.handler.config import ConfigError, load_settings


def test_load_settings_requires_tokens(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        _ = load_settings({"LMNOP_HANDLER_VAULT_ROOT": str(tmp_path)})


def test_load_settings_rejects_invalid_tokens(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        _ = load_settings(
            {
                "LMNOP_HANDLER_VAULT_ROOT": str(tmp_path),
                "LMNOP_HANDLER_BEARER_TOKENS": "[]",
            }
        )


def test_configured_token_verifier_accepts_valid_token() -> None:
    verifier = ConfiguredTokenVerifier(lambda: {"client": "secret"})

    async def run() -> None:
        assert await verifier.verify_token("wrong") is None
        token = await verifier.verify_token("secret")
        assert token is not None
        assert token.client_id == "client"

    asyncio.run(run())
