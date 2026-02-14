"""Tests for src.auth — BearerTokenVerifier."""

import pytest

from src.auth import BearerTokenVerifier

# A valid token (>= 32 chars)
VALID_TOKEN = "a" * 48


class TestBearerTokenVerifier:
    """BearerTokenVerifier unit tests."""

    def test_short_token_raises(self):
        """Tokens shorter than 32 characters must be rejected at construction."""
        with pytest.raises(ValueError, match="at least 32 characters"):
            BearerTokenVerifier("short")

    def test_empty_token_raises(self):
        """Empty string must be rejected at construction."""
        with pytest.raises(ValueError, match="at least 32 characters"):
            BearerTokenVerifier("")

    async def test_valid_token_returns_access_token(self):
        """A matching bearer token returns an AccessToken."""
        verifier = BearerTokenVerifier(VALID_TOKEN)
        result = await verifier.verify_token(VALID_TOKEN)
        assert result is not None
        assert result.client_id == "owner"
        assert result.scopes == []

    async def test_invalid_token_returns_none(self):
        """A non-matching bearer token returns None."""
        verifier = BearerTokenVerifier(VALID_TOKEN)
        result = await verifier.verify_token("wrong-token-that-is-definitely-not-right")
        assert result is None
