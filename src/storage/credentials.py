"""Fernet-encrypted credential storage for booking platforms."""

import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "restaurant-mcp"
_KEYRING_KEY_NAME = "fernet-key"


class CredentialStore:
    """Encrypt and store platform credentials on disk.

    Key storage priority:
    1. OS keyring (macOS Keychain / Linux Secret Service) — if ``keyring`` is installed
    2. File-based fallback at ``credentials_dir / ".key"``

    Each platform's encrypted JSON is at ``credentials_dir / "{platform}.enc"``.

    Args:
        credentials_dir: Directory for key and encrypted files.
    """

    def __init__(self, credentials_dir: Path) -> None:
        self.credentials_dir = credentials_dir
        self.credentials_dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self.credentials_dir / ".key"
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        """Return (and cache) the Fernet instance, generating a key if needed.

        Tries OS keyring first, then falls back to file-based key storage.
        """
        if self._fernet is not None:
            return self._fernet

        # Try keyring first
        key = self._load_key_from_keyring()
        if key is not None:
            self._fernet = Fernet(key)
            return self._fernet

        # Fall back to file
        key = self._load_key_from_file()
        self._fernet = Fernet(key)
        return self._fernet

    def _load_key_from_keyring(self) -> bytes | None:
        """Try to load the Fernet key from OS keyring.

        If no key exists in keyring but a ``.key`` file exists, migrates
        the file key to keyring and deletes the file.

        Returns:
            Key bytes, or None if keyring is unavailable.
        """
        try:
            import keyring as kr
        except ImportError:
            return None

        try:
            stored = kr.get_password(_KEYRING_SERVICE, _KEYRING_KEY_NAME)
            if stored is not None:
                return stored.encode()

            # No key in keyring — check for existing .key file to migrate
            if self._key_path.exists():
                key = self._key_path.read_bytes()
                kr.set_password(_KEYRING_SERVICE, _KEYRING_KEY_NAME, key.decode())
                self._key_path.unlink()
                logger.info("Migrated Fernet key from file to OS keyring")
                return key

            # Generate a new key and store in keyring
            key = Fernet.generate_key()
            kr.set_password(_KEYRING_SERVICE, _KEYRING_KEY_NAME, key.decode())
            logger.info("Generated new Fernet key in OS keyring")
            return key
        except Exception:  # noqa: BLE001
            logger.debug("Keyring unavailable, falling back to file-based key")
            return None

    def _load_key_from_file(self) -> bytes:
        """Load or generate the Fernet key from a file."""
        if self._key_path.exists():
            key = self._key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)
        self._secure_path(self._key_path)
        return key

    def _enc_path(self, platform: str) -> Path:
        return self.credentials_dir / f"{platform}.enc"

    def _secure_path(self, path: Path) -> None:
        """Set restrictive permissions on a path.

        Directories get 0o700, files get 0o600.
        """
        try:
            if path.is_dir():
                os.chmod(path, 0o700)
            else:
                os.chmod(path, 0o600)
        except OSError:
            logger.debug("Could not set permissions on %s", path)

    def save_credentials(self, platform: str, data: dict) -> None:
        """Encrypt and save credentials for a platform."""
        fernet = self._get_fernet()
        plaintext = json.dumps(data).encode()
        encrypted = fernet.encrypt(plaintext)
        enc_path = self._enc_path(platform)
        enc_path.write_bytes(encrypted)
        self._secure_path(enc_path)
        self._secure_path(self.credentials_dir)
        logger.info("Credentials saved for %s", platform)

    def get_credentials(self, platform: str) -> dict | None:
        """Decrypt and return credentials, or None if not stored."""
        path = self._enc_path(platform)
        if not path.exists():
            return None
        fernet = self._get_fernet()
        try:
            decrypted = fernet.decrypt(path.read_bytes())
        except InvalidToken:
            logger.warning("Failed to decrypt credentials for %s", platform)
            return None
        return json.loads(decrypted)

    def delete_credentials(self, platform: str) -> None:
        """Remove stored credentials for a platform."""
        path = self._enc_path(platform)
        if path.exists():
            path.unlink()
            logger.info("Credentials deleted for %s", platform)

    def has_credentials(self, platform: str) -> bool:
        """Check if credentials exist for a platform."""
        return self._enc_path(platform).exists()
