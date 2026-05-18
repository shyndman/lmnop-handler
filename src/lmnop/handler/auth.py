from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from typing import override

from fastmcp.server.auth import AccessToken, TokenVerifier

TokenLoader = Callable[[], Mapping[str, str]]


class ConfiguredTokenVerifier(TokenVerifier):
    _token_loader: TokenLoader

    def __init__(self, token_loader: TokenLoader):
        super().__init__()
        self._token_loader = token_loader

    @override
    async def verify_token(self, token: str) -> AccessToken | None:
        for client_id, expected in self._token_loader().items():
            if secrets.compare_digest(token, expected):
                return AccessToken(
                    token=token,
                    client_id=client_id,
                    scopes=[],
                    claims={"client_id": client_id},
                )
        return None
