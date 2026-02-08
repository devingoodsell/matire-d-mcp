"""Tests for encrypted ConfigStore (master-key mode)."""

import aiosqlite
from cryptography.fernet import Fernet

from src.storage.config_store import ConfigStore, derive_fernet_key

# ── derive_fernet_key ────────────────────────────────────────────────────


class TestDeriveFernetKey:
    def test_returns_valid_fernet_key(self):
        key = derive_fernet_key("my-secret-master-key")
        # Must not raise
        Fernet(key)

    def test_deterministic(self):
        k1 = derive_fernet_key("same")
        k2 = derive_fernet_key("same")
        assert k1 == k2

    def test_different_inputs_different_keys(self):
        k1 = derive_fernet_key("key-a")
        k2 = derive_fernet_key("key-b")
        assert k1 != k2


# ── ConfigStore ──────────────────────────────────────────────────────────


async def _make_store(master_key: str = "test-master") -> tuple[ConfigStore, aiosqlite.Connection]:
    """Create an in-memory DB with schema and return (store, conn)."""
    from pathlib import Path

    conn = await aiosqlite.connect(":memory:")
    schema_path = Path(__file__).resolve().parent.parent.parent / "src" / "storage" / "schema.sql"
    schema = schema_path.read_text()
    await conn.executescript(schema)
    await conn.commit()
    store = ConfigStore(conn, master_key)
    return store, conn


class TestSetAndGet:
    async def test_round_trip(self):
        store, conn = await _make_store()
        await store.set("google_api_key", "AIza-test-key")
        result = await store.get("google_api_key")
        assert result == "AIza-test-key"
        await conn.close()

    async def test_get_missing_key_returns_none(self):
        store, conn = await _make_store()
        result = await store.get("nonexistent")
        assert result is None
        await conn.close()

    async def test_upsert_overwrites_existing(self):
        store, conn = await _make_store()
        await store.set("key", "old-value")
        await store.set("key", "new-value")
        result = await store.get("key")
        assert result == "new-value"
        await conn.close()

    async def test_values_are_encrypted_in_db(self):
        store, conn = await _make_store()
        await store.set("secret", "plaintext-value")

        cursor = await conn.execute("SELECT value FROM app_config WHERE key = ?", ("secret",))
        row = await cursor.fetchone()
        raw = row[0]
        # Raw value is encrypted — should NOT be the plaintext
        assert raw != b"plaintext-value"
        assert b"plaintext-value" not in raw
        await conn.close()

    async def test_wrong_master_key_returns_none(self):
        store1, conn = await _make_store("correct-key")
        await store1.set("secret", "sensitive")

        store2 = ConfigStore(conn, "wrong-key")
        result = await store2.get("secret")
        assert result is None
        await conn.close()


class TestDelete:
    async def test_delete_existing_key(self):
        store, conn = await _make_store()
        await store.set("key", "value")
        await store.delete("key")
        result = await store.get("key")
        assert result is None
        await conn.close()

    async def test_delete_nonexistent_key_no_error(self):
        store, conn = await _make_store()
        await store.delete("nonexistent")  # should not raise
        await conn.close()


class TestHas:
    async def test_has_returns_true(self):
        store, conn = await _make_store()
        await store.set("key", "value")
        assert await store.has("key") is True
        await conn.close()

    async def test_has_returns_false(self):
        store, conn = await _make_store()
        assert await store.has("nonexistent") is False
        await conn.close()


class TestGetAll:
    async def test_returns_all_entries(self):
        store, conn = await _make_store()
        await store.set("a", "1")
        await store.set("b", "2")
        await store.set("c", "3")
        result = await store.get_all()
        assert result == {"a": "1", "b": "2", "c": "3"}
        await conn.close()

    async def test_empty_returns_empty_dict(self):
        store, conn = await _make_store()
        result = await store.get_all()
        assert result == {}
        await conn.close()

    async def test_skips_corrupted_entries(self):
        store, conn = await _make_store()
        await store.set("good", "value")
        # Insert a corrupted entry directly
        await conn.execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?)",
            ("bad", b"not-encrypted"),
        )
        await conn.commit()
        result = await store.get_all()
        assert result == {"good": "value"}
        await conn.close()


class TestJson:
    async def test_set_and_get_json(self):
        store, conn = await _make_store()
        data = {"email": "a@b.com", "token": "tok123"}
        await store.set_json("resy_creds", data)
        result = await store.get_json("resy_creds")
        assert result == data
        await conn.close()

    async def test_get_json_missing_returns_none(self):
        store, conn = await _make_store()
        result = await store.get_json("nonexistent")
        assert result is None
        await conn.close()

    async def test_set_json_with_list(self):
        store, conn = await _make_store()
        await store.set_json("items", [1, 2, 3])
        result = await store.get_json("items")
        assert result == [1, 2, 3]
        await conn.close()
