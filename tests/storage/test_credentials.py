"""Tests for Fernet-encrypted credential storage."""

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

from src.storage.credentials import CredentialStore


class TestInit:
    def test_creates_directory_if_not_exists(self, tmp_path: Path):
        creds_dir = tmp_path / "subdir" / "credentials"
        assert not creds_dir.exists()
        CredentialStore(creds_dir)
        assert creds_dir.is_dir()

    def test_existing_directory_is_fine(self, tmp_path: Path):
        creds_dir = tmp_path / "credentials"
        creds_dir.mkdir()
        store = CredentialStore(creds_dir)
        assert store.credentials_dir == creds_dir


class TestSaveAndGetCredentials:
    def test_round_trip(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        data = {"username": "alice", "password": "s3cret"}
        store.save_credentials("resy", data)
        result = store.get_credentials("resy")
        assert result == data

    def test_get_missing_platform_returns_none(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        assert store.get_credentials("nonexistent") is None

    def test_get_corrupted_data_returns_none(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        # Write invalid encrypted data directly to the file
        enc_path = store._enc_path("resy")
        enc_path.write_bytes(b"this-is-not-valid-encrypted-data")
        result = store.get_credentials("resy")
        assert result is None


class TestHasCredentials:
    def test_returns_true_when_saved(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        store.save_credentials("resy", {"token": "abc"})
        assert store.has_credentials("resy") is True

    def test_returns_false_when_not_saved(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        assert store.has_credentials("resy") is False


class TestDeleteCredentials:
    def test_removes_the_file(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        store.save_credentials("resy", {"token": "abc"})
        assert store.has_credentials("resy") is True
        store.delete_credentials("resy")
        assert store.has_credentials("resy") is False

    def test_nonexistent_platform_does_not_raise(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        store.delete_credentials("nonexistent")  # should not raise


class TestKeyManagement:
    def test_key_generated_on_first_use_and_reused(self, tmp_path: Path):
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)
        key_path = creds_dir / ".key"

        # No key file before first use
        assert not key_path.exists()

        # Force file-based storage by making keyring unavailable
        with patch.dict("sys.modules", {"keyring": None}):
            store.save_credentials("resy", {"token": "abc"})

        # Key file now exists
        assert key_path.exists()
        key_bytes = key_path.read_bytes()

        # Second call reuses the cached Fernet (same instance)
        fernet1 = store._get_fernet()
        fernet2 = store._get_fernet()
        assert fernet1 is fernet2

        # Key file unchanged on disk
        assert key_path.read_bytes() == key_bytes

    def test_key_loaded_from_disk_on_new_instance(self, tmp_path: Path):
        creds_dir = tmp_path / "creds"

        # Force file-based storage by making keyring unavailable
        with patch.dict("sys.modules", {"keyring": None}):
            store1 = CredentialStore(creds_dir)
            store1.save_credentials("resy", {"token": "abc"})

            # New instance should load the existing key and decrypt successfully
            store2 = CredentialStore(creds_dir)
            result = store2.get_credentials("resy")
        assert result == {"token": "abc"}


class TestMultiplePlatforms:
    def test_independent_storage(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds")
        resy_data = {"username": "alice", "api_key": "resy_key"}
        opentable_data = {"email": "alice@example.com", "password": "ot_pass"}

        store.save_credentials("resy", resy_data)
        store.save_credentials("opentable", opentable_data)

        assert store.get_credentials("resy") == resy_data
        assert store.get_credentials("opentable") == opentable_data

        # Deleting one does not affect the other
        store.delete_credentials("resy")
        assert store.get_credentials("resy") is None
        assert store.get_credentials("opentable") == opentable_data


class TestKeyringIntegration:
    """Test keyring-based key management (mocked)."""

    def test_keyring_stores_and_retrieves_key(self, tmp_path: Path):
        """When keyring is available and has a key, it is used."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)

        key = Fernet.generate_key()
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = key.decode()

        with patch.dict("sys.modules", {"keyring": mock_kr}):
            result = store._load_key_from_keyring()

        assert result == key
        mock_kr.get_password.assert_called_once_with("restaurant-mcp", "fernet-key")

    def test_keyring_generates_new_key_when_empty(self, tmp_path: Path):
        """When keyring has no key and no .key file, a new key is generated."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)

        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None

        with patch.dict("sys.modules", {"keyring": mock_kr}):
            result = store._load_key_from_keyring()

        assert result is not None
        # Key was stored in keyring
        mock_kr.set_password.assert_called_once()
        call_args = mock_kr.set_password.call_args[0]
        assert call_args[0] == "restaurant-mcp"
        assert call_args[1] == "fernet-key"
        # Verify it's a valid Fernet key
        Fernet(result)

    def test_keyring_migrates_existing_key_file(self, tmp_path: Path):
        """When keyring has no key but .key file exists, migrates to keyring."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)

        # Create an existing key file
        key = Fernet.generate_key()
        store._key_path.write_bytes(key)

        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None

        with patch.dict("sys.modules", {"keyring": mock_kr}):
            result = store._load_key_from_keyring()

        assert result == key
        mock_kr.set_password.assert_called_once_with(
            "restaurant-mcp", "fernet-key", key.decode()
        )
        # .key file should be deleted after migration
        assert not store._key_path.exists()

    def test_keyring_unavailable_falls_back_to_file(self, tmp_path: Path):
        """When keyring import fails, returns None (triggers file fallback)."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)

        with patch.dict("sys.modules", {"keyring": None}):
            result = store._load_key_from_keyring()

        assert result is None

    def test_keyring_error_falls_back_to_file(self, tmp_path: Path):
        """When keyring raises an exception, returns None."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)

        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = RuntimeError("keyring broken")

        with patch.dict("sys.modules", {"keyring": mock_kr}):
            result = store._load_key_from_keyring()

        assert result is None

    def test_full_round_trip_with_keyring(self, tmp_path: Path):
        """End-to-end: save and load credentials using keyring for key storage."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)

        stored_key = {}
        mock_kr = MagicMock()

        def fake_get(service, name):
            return stored_key.get(f"{service}:{name}")

        def fake_set(service, name, value):
            stored_key[f"{service}:{name}"] = value

        mock_kr.get_password.side_effect = fake_get
        mock_kr.set_password.side_effect = fake_set

        with patch.dict("sys.modules", {"keyring": mock_kr}):
            store.save_credentials("resy", {"token": "abc"})
            result = store.get_credentials("resy")

        assert result == {"token": "abc"}
        # No .key file should exist (keyring was used)
        assert not store._key_path.exists()


class TestFilePermissions:
    """Test that restrictive permissions are set on files and directories."""

    def test_key_file_permissions(self, tmp_path: Path):
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)
        with patch.dict("sys.modules", {"keyring": None}):
            store.save_credentials("resy", {"token": "abc"})

        key_path = creds_dir / ".key"
        mode = stat.S_IMODE(os.stat(key_path).st_mode)
        assert mode == 0o600

    def test_enc_file_permissions(self, tmp_path: Path):
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)
        with patch.dict("sys.modules", {"keyring": None}):
            store.save_credentials("resy", {"token": "abc"})

        enc_path = creds_dir / "resy.enc"
        mode = stat.S_IMODE(os.stat(enc_path).st_mode)
        assert mode == 0o600

    def test_dir_permissions(self, tmp_path: Path):
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)
        with patch.dict("sys.modules", {"keyring": None}):
            store.save_credentials("resy", {"token": "abc"})

        mode = stat.S_IMODE(os.stat(creds_dir).st_mode)
        assert mode == 0o700

    def test_secure_path_handles_oserror(self, tmp_path: Path):
        """_secure_path swallows OSError gracefully."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)

        with patch("os.chmod", side_effect=OSError("permission denied")):
            # Should not raise
            store._secure_path(creds_dir / "nonexistent")

    def test_secure_path_on_directory(self, tmp_path: Path):
        """_secure_path sets 0o700 on directories."""
        creds_dir = tmp_path / "creds"
        store = CredentialStore(creds_dir)
        store._secure_path(creds_dir)

        mode = stat.S_IMODE(os.stat(creds_dir).st_mode)
        assert mode == 0o700
