"""Encrypted application config stored in SQLite via a master key."""

import base64
import hashlib
import json
import logging

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PBKDF2_SALT = b"restaurant-mcp-v1"
_PBKDF2_ITERATIONS = 100_000


def derive_fernet_key(master_key: str) -> bytes:
    """Derive a Fernet-compatible key from a master key string via PBKDF2."""
    dk = hashlib.pbkdf2_hmac(
        "sha256", master_key.encode(), _PBKDF2_SALT, _PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(dk)


class ConfigStore:
    """Read/write encrypted config values from the ``app_config`` table.

    Args:
        connection: An open aiosqlite connection (shared with DatabaseManager).
        master_key: The plaintext master key used to derive the Fernet key.
    """

    def __init__(self, connection: aiosqlite.Connection, master_key: str) -> None:
        self.connection = connection
        self._fernet = Fernet(derive_fernet_key(master_key))

    async def get(self, key: str) -> str | None:
        """Return the decrypted value for *key*, or ``None`` if missing."""
        cursor = await self.connection.execute(
            "SELECT value FROM app_config WHERE key = ?", (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row[0]).decode()
        except InvalidToken:
            logger.warning("Failed to decrypt config key %s", key)
            return None

    async def set(self, key: str, value: str) -> None:
        """Encrypt and store *value* under *key* (upsert)."""
        encrypted = self._fernet.encrypt(value.encode())
        await self.connection.execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, encrypted),
        )
        await self.connection.commit()

    async def delete(self, key: str) -> None:
        """Remove a config entry."""
        await self.connection.execute("DELETE FROM app_config WHERE key = ?", (key,))
        await self.connection.commit()

    async def has(self, key: str) -> bool:
        """Check whether *key* exists."""
        cursor = await self.connection.execute(
            "SELECT 1 FROM app_config WHERE key = ?", (key,),
        )
        return await cursor.fetchone() is not None

    async def get_all(self) -> dict[str, str]:
        """Return all decrypted config entries as a dict."""
        cursor = await self.connection.execute("SELECT key, value FROM app_config")
        rows = await cursor.fetchall()
        result: dict[str, str] = {}
        for row in rows:
            try:
                result[row[0]] = self._fernet.decrypt(row[1]).decode()
            except InvalidToken:
                logger.warning("Failed to decrypt config key %s", row[0])
        return result

    async def set_json(self, key: str, value: object) -> None:
        """Serialize *value* as JSON and store encrypted."""
        await self.set(key, json.dumps(value))

    async def get_json(self, key: str) -> object | None:
        """Return the deserialized JSON value, or ``None``."""
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)
