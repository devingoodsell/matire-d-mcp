"""Bearer token authentication for remote MCP access.

Provides a simple pre-shared-token verifier using FastMCP's ``TokenVerifier``
base class.  When ``auth=`` is set on the ``FastMCP`` instance the library
automatically wires ``BearerAuthBackend`` + ``RequireAuthMiddleware`` onto
the MCP endpoint — no custom ASGI middleware needed.
"""

import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier

_MIN_TOKEN_LENGTH = 32


class BearerTokenVerifier(TokenVerifier):
    """Verify incoming bearer tokens against a pre-shared secret.

    Args:
        token: The expected bearer token (must be >= 32 characters).

    Raises:
        ValueError: If *token* is empty or shorter than 32 characters.
    """

    def __init__(self, token: str) -> None:
        if not token or len(token) < _MIN_TOKEN_LENGTH:
            raise ValueError(
                f"MCP auth token must be at least {_MIN_TOKEN_LENGTH} characters, "
                f"got {len(token) if token else 0}"
            )
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return an ``AccessToken`` when *token* matches, ``None`` otherwise.

        Uses ``hmac.compare_digest`` for constant-time comparison to prevent
        timing-based side-channel attacks.
        """
        if hmac.compare_digest(token, self._token):
            return AccessToken(token=token, client_id="owner", scopes=[])
        return None
