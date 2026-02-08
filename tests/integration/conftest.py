"""Shared fixtures for integration tests (live API calls).

Credentials are loaded from the encrypted credential store on disk
(``data/.credentials/{resy,opentable}.enc``), matching what the
production server uses.  Environment variables can override test
parameters.

Optional env vars:
    INTEGRATION_RESTAURANT    — restaurant name (default: "Carbone")
    INTEGRATION_DATE          — date YYYY-MM-DD (default: 14 days from now)
    INTEGRATION_PARTY_SIZE    — party size (default: 2)
    INTEGRATION_RESY_VENUE_ID — Resy venue ID (skip search if set)
    INTEGRATION_OT_SLUG       — OpenTable slug (skip search if set)
"""

import datetime
import os

import pytest

from src.clients.opentable import OpenTableClient
from src.clients.resy import ResyClient
from src.config import get_settings
from src.storage.credentials import CredentialStore

# ---------------------------------------------------------------------------
# Credential store (shared across fixtures)
# ---------------------------------------------------------------------------


def _get_credential_store() -> CredentialStore:
    """Return the production CredentialStore (data/.credentials/)."""
    settings = get_settings()
    return CredentialStore(settings.credentials_path)


# ---------------------------------------------------------------------------
# Test parameters
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_restaurant() -> dict:
    """Return {name, date, party_size} from env or defaults."""
    default_date = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=14)
    ).strftime("%Y-%m-%d")
    return {
        "name": os.environ.get("INTEGRATION_RESTAURANT", "Superiority Burger"),
        "date": os.environ.get("INTEGRATION_DATE", default_date),
        "party_size": int(os.environ.get("INTEGRATION_PARTY_SIZE", "2")),
        "resy_venue_id": os.environ.get("INTEGRATION_RESY_VENUE_ID"),
        "ot_slug": os.environ.get("INTEGRATION_OT_SLUG"),
    }


# ---------------------------------------------------------------------------
# Resy fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def resy_credentials() -> dict:
    """Load Resy credentials from the encrypted credential store."""
    store = _get_credential_store()
    creds = store.get_credentials("resy")
    if not creds or not creds.get("auth_token"):
        pytest.skip("No Resy credentials in credential store (run setup first)")
    return creds


@pytest.fixture(scope="session")
def resy_client(resy_credentials: dict) -> ResyClient:
    """Return a pre-authenticated ResyClient."""
    return ResyClient(
        api_key=resy_credentials.get("api_key", ResyClient.__init__.__defaults__[0]),
        auth_token=resy_credentials["auth_token"],
    )


# ---------------------------------------------------------------------------
# OpenTable fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ot_credentials() -> dict:
    """Load OpenTable credentials from the encrypted credential store."""
    store = _get_credential_store()
    creds = store.get_credentials("opentable")
    if not creds or not creds.get("csrf_token"):
        pytest.skip("No OpenTable credentials in credential store (run setup first)")
    return creds


@pytest.fixture(scope="session")
def ot_client() -> OpenTableClient:
    """Return an OpenTableClient backed by the production credential store."""
    store = _get_credential_store()
    return OpenTableClient(store)


# ---------------------------------------------------------------------------
# Cleanup: cancel any leftover reservations
# ---------------------------------------------------------------------------

_resy_tokens_to_cancel: list[str] = []
_ot_confirmations_to_cancel: list[str] = []


@pytest.fixture(scope="session")
def resy_cleanup():
    """Provide a list to register resy_tokens for cleanup."""
    return _resy_tokens_to_cancel


@pytest.fixture(scope="session")
def ot_cleanup():
    """Provide a list to register OT confirmation numbers for cleanup."""
    return _ot_confirmations_to_cancel


@pytest.fixture(scope="session", autouse=True)
def _session_finalizer(request):
    """Cancel any leftover reservations at the end of the test session."""
    store = _get_credential_store()
    resy_creds = store.get_credentials("resy")
    ot_client_cleanup = OpenTableClient(store)

    def _finalise():
        import asyncio

        async def _do_cleanup():
            if resy_creds and resy_creds.get("auth_token"):
                client = ResyClient(
                    api_key=resy_creds.get("api_key", ""),
                    auth_token=resy_creds["auth_token"],
                )
                for token in _resy_tokens_to_cancel:
                    try:
                        await client.cancel(token)
                    except Exception:  # noqa: BLE001
                        pass
            for conf in _ot_confirmations_to_cancel:
                try:
                    await ot_client_cleanup.cancel(conf)
                except Exception:  # noqa: BLE001
                    pass
            await ot_client_cleanup.close()

        asyncio.get_event_loop().run_until_complete(_do_cleanup())

    request.addfinalizer(_finalise)
