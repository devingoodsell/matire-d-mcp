"""Tests for Fernet-encrypted credential storage."""

from pathlib import Path

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
