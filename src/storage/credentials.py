"""Fernet-encrypted credential storage for booking platforms."""

import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CredentialStore:
    """Encrypt and store platform credentials on disk.

    Key is stored at ``credentials_dir / ".key"``.
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
        """Return (and cache) the Fernet instance, generating a key if needed."""
        if self._fernet is not None:
            return self._fernet
        if self._key_path.exists():
            key = self._key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)
        self._fernet = Fernet(key)
        return self._fernet

    def _enc_path(self, platform: str) -> Path:
        return self.credentials_dir / f"{platform}.enc"

    def save_credentials(self, platform: str, data: dict) -> None:
        """Encrypt and save credentials for a platform."""
        fernet = self._get_fernet()
        plaintext = json.dumps(data).encode()
        encrypted = fernet.encrypt(plaintext)
        self._enc_path(platform).write_bytes(encrypted)
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
