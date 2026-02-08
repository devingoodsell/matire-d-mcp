"""Resilience primitives: exception hierarchy, retry, circuit breaker, schema validation."""

import logging
import time
from enum import StrEnum

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ── Exception Hierarchy ──────────────────────────────────────────────────────


class APIError(Exception):
    """Base class for all API errors."""


class TransientAPIError(APIError):
    """Retriable errors (429, 5xx)."""


class PermanentAPIError(APIError):
    """Non-retriable errors (403, 404, etc.)."""


class AuthError(PermanentAPIError):
    """Authentication/authorisation failure (401)."""


class SchemaChangeError(PermanentAPIError):
    """Remote API response shape changed unexpectedly."""


class CAPTCHAError(PermanentAPIError):
    """CAPTCHA challenge detected."""


class CircuitOpenError(APIError):
    """Circuit breaker is open — calls are being shed."""


TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


# ── Response Classification ──────────────────────────────────────────────────


def classify_response(response: object) -> None:
    """Raise an appropriate error based on HTTP status code.

    Args:
        response: An object with a ``status_code`` attribute (e.g. httpx.Response).

    Raises:
        AuthError: On 401.
        PermanentAPIError: On 403, 404.
        TransientAPIError: On 429, 5xx.
    """
    status = getattr(response, "status_code", None)
    if status is None or 200 <= status < 400:
        return

    if status == 401:
        raise AuthError(f"Authentication failed (HTTP {status})")
    if status in TRANSIENT_STATUS_CODES:
        raise TransientAPIError(f"Transient error (HTTP {status})")
    if 400 <= status < 500:
        raise PermanentAPIError(f"Client error (HTTP {status})")
    raise TransientAPIError(f"Server error (HTTP {status})")


# ── Retry ─────────────────────────────────────────────────────────────────


def log_retry_attempt(retry_state: RetryCallState) -> None:
    """Tenacity ``before_sleep`` callback that logs each retry."""
    attempt = retry_state.attempt_number
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning("Retry attempt %d after error: %s", attempt, exc)


resilient_request = retry(
    retry=retry_if_exception_type(TransientAPIError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    before_sleep=log_retry_attempt,
    reraise=True,
)
"""Tenacity decorator for retrying on ``TransientAPIError``."""


# ── Circuit Breaker ──────────────────────────────────────────────────────────


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Lightweight async circuit breaker (no external dependency).

    Args:
        name: Human-readable name for logging.
        fail_max: Consecutive failures before opening.
        reset_timeout: Seconds to wait before trying again (half-open).
    """

    def __init__(
        self, name: str, fail_max: int = 5, reset_timeout: float = 60.0
    ) -> None:
        self.name = name
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout

        self._state = CircuitState.CLOSED
        self._fail_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.reset_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    async def call_async(self, coro):  # type: ignore[no-untyped-def]
        """Execute *coro*, applying circuit-breaker logic.

        Raises:
            CircuitOpenError: If the circuit is OPEN.
        """
        current = self.state
        if current == CircuitState.OPEN:
            raise CircuitOpenError(f"Circuit '{self.name}' is open")

        try:
            result = await coro
        except Exception:
            self._fail_count += 1
            self._last_failure_time = time.monotonic()
            if self._fail_count >= self.fail_max:
                self._state = CircuitState.OPEN
                logger.warning("Circuit '%s' opened after %d failures", self.name, self._fail_count)
            elif current == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("Circuit '%s' re-opened on half-open failure", self.name)
            raise

        # Success — reset
        self._fail_count = 0
        self._state = CircuitState.CLOSED
        return result


# Pre-configured breakers
resy_breaker = CircuitBreaker("resy", fail_max=5, reset_timeout=60.0)
google_places_breaker = CircuitBreaker("google_places", fail_max=5, reset_timeout=60.0)
opentable_breaker = CircuitBreaker("opentable", fail_max=5, reset_timeout=60.0)
weather_breaker = CircuitBreaker("weather", fail_max=3, reset_timeout=120.0)


# ── Schema Validation ────────────────────────────────────────────────────────


def validate_resy_availability_schema(data: dict) -> None:
    """Validate that a Resy availability response has expected keys.

    Raises:
        SchemaChangeError: If required keys are missing.
    """
    if not isinstance(data, dict):
        raise SchemaChangeError("Expected dict for Resy availability response")
    required = {"results"}
    missing = required - data.keys()
    if missing:
        raise SchemaChangeError(f"Missing keys in Resy availability: {missing}")


def validate_resy_details_schema(data: dict) -> None:
    """Validate that a Resy booking-details response has expected keys.

    Raises:
        SchemaChangeError: If required keys are missing.
    """
    if not isinstance(data, dict):
        raise SchemaChangeError("Expected dict for Resy details response")
    required = {"book_token"}
    missing = required - data.keys()
    if missing:
        raise SchemaChangeError(f"Missing keys in Resy details: {missing}")
