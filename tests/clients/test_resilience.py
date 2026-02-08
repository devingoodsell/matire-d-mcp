"""Tests for src.clients.resilience — exceptions, retry, circuit breaker, schema validation."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.clients.resilience import (
    TRANSIENT_STATUS_CODES,
    AuthError,
    CAPTCHAError,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    PermanentAPIError,
    SchemaChangeError,
    TransientAPIError,
    classify_response,
    google_places_breaker,
    log_retry_attempt,
    opentable_breaker,
    resilient_request,
    resy_breaker,
    validate_resy_availability_schema,
    validate_resy_details_schema,
    weather_breaker,
)

# ── Exception Hierarchy ──────────────────────────────────────────────────────


class TestExceptionHierarchy:
    def test_transient_is_api_error(self):
        assert issubclass(TransientAPIError, Exception)

    def test_permanent_is_api_error(self):
        assert issubclass(PermanentAPIError, Exception)

    def test_auth_is_permanent(self):
        assert issubclass(AuthError, PermanentAPIError)

    def test_schema_change_is_permanent(self):
        assert issubclass(SchemaChangeError, PermanentAPIError)

    def test_captcha_is_permanent(self):
        assert issubclass(CAPTCHAError, PermanentAPIError)

    def test_circuit_open_is_api_error(self):
        from src.clients.resilience import APIError

        assert issubclass(CircuitOpenError, APIError)


# ── classify_response ────────────────────────────────────────────────────────


class TestClassifyResponse:
    def test_200_no_error(self):
        resp = MagicMock(status_code=200)
        classify_response(resp)  # Should not raise

    def test_301_no_error(self):
        resp = MagicMock(status_code=301)
        classify_response(resp)

    def test_401_raises_auth_error(self):
        resp = MagicMock(status_code=401)
        with pytest.raises(AuthError, match="401"):
            classify_response(resp)

    def test_403_raises_permanent(self):
        resp = MagicMock(status_code=403)
        with pytest.raises(PermanentAPIError, match="403"):
            classify_response(resp)

    def test_404_raises_permanent(self):
        resp = MagicMock(status_code=404)
        with pytest.raises(PermanentAPIError, match="404"):
            classify_response(resp)

    @pytest.mark.parametrize("code", sorted(TRANSIENT_STATUS_CODES))
    def test_transient_codes(self, code):
        resp = MagicMock(status_code=code)
        with pytest.raises(TransientAPIError):
            classify_response(resp)

    def test_unknown_5xx_is_transient(self):
        resp = MagicMock(status_code=599)
        with pytest.raises(TransientAPIError):
            classify_response(resp)

    def test_no_status_code_attribute(self):
        classify_response(object())  # No status_code → no-op

    def test_none_status_code(self):
        resp = MagicMock(status_code=None)
        classify_response(resp)


# ── log_retry_attempt ────────────────────────────────────────────────────────


class TestLogRetryAttempt:
    def test_logs_retry_info(self):
        state = MagicMock()
        state.attempt_number = 2
        state.outcome.exception.return_value = TransientAPIError("boom")
        with patch("src.clients.resilience.logger") as mock_logger:
            log_retry_attempt(state)
            mock_logger.warning.assert_called_once()
            assert "2" in str(mock_logger.warning.call_args)

    def test_logs_with_no_outcome(self):
        state = MagicMock()
        state.attempt_number = 1
        state.outcome = None
        with patch("src.clients.resilience.logger") as mock_logger:
            log_retry_attempt(state)
            mock_logger.warning.assert_called_once()


# ── resilient_request ────────────────────────────────────────────────────────


class TestResilientRequest:
    def test_decorator_config(self):
        # resilient_request is a tenacity retry object usable as a decorator
        assert callable(resilient_request)

    async def test_successful_call_passes_through(self):
        @resilient_request
        async def success():
            return "ok"

        assert await success() == "ok"

    async def test_permanent_error_not_retried(self):
        call_count = 0

        @resilient_request
        async def fail_permanent():
            nonlocal call_count
            call_count += 1
            raise PermanentAPIError("bad")

        with pytest.raises(PermanentAPIError):
            await fail_permanent()
        assert call_count == 1


# ── CircuitBreaker ───────────────────────────────────────────────────────────


class TestCircuitBreaker:
    async def test_closed_passes_through(self):
        cb = CircuitBreaker("test", fail_max=3, reset_timeout=1.0)

        async def success():
            return "ok"

        result = await cb.call_async(success())
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    async def test_opens_after_fail_max(self):
        cb = CircuitBreaker("test", fail_max=2, reset_timeout=60.0)

        async def fail():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call_async(fail())

        assert cb.state == CircuitState.OPEN

    async def test_open_raises_circuit_open_error(self):
        cb = CircuitBreaker("test", fail_max=1, reset_timeout=60.0)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call_async(fail())

        assert cb.state == CircuitState.OPEN

        # state check happens before coro is evaluated, so this will
        # raise CircuitOpenError without ever awaiting the coro.
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with pytest.raises(CircuitOpenError, match="test"):
                await cb.call_async(asyncio.sleep(0))

    async def test_half_open_after_timeout(self):
        cb = CircuitBreaker("test", fail_max=1, reset_timeout=0.01)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call_async(fail())

        assert cb.state == CircuitState.OPEN

        # Wait for reset timeout
        await asyncio.sleep(0.02)

        assert cb.state == CircuitState.HALF_OPEN

    async def test_half_open_success_resets_to_closed(self):
        cb = CircuitBreaker("test", fail_max=1, reset_timeout=0.01)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call_async(fail())

        await asyncio.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        async def success():
            return "recovered"

        result = await cb.call_async(success())
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    async def test_half_open_failure_returns_to_open(self):
        cb = CircuitBreaker("test", fail_max=2, reset_timeout=0.01)

        async def fail():
            raise ValueError("boom")

        # Push to OPEN state (need fail_max=2 failures)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call_async(fail())

        assert cb._state == CircuitState.OPEN
        await asyncio.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        # Reset fail count so next failure hits the elif branch
        # (fail_count will be 3, but current is HALF_OPEN)
        cb._fail_count = 0

        with pytest.raises(ValueError):
            await cb.call_async(fail())

        # Should re-open via the elif branch (current was HALF_OPEN, fail_count < fail_max)
        assert cb._state == CircuitState.OPEN

    async def test_success_resets_fail_count(self):
        cb = CircuitBreaker("test", fail_max=3, reset_timeout=60.0)

        async def fail():
            raise ValueError("boom")

        async def success():
            return "ok"

        # 2 failures (below fail_max of 3)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call_async(fail())

        assert cb._fail_count == 2

        # Success resets
        await cb.call_async(success())
        assert cb._fail_count == 0
        assert cb.state == CircuitState.CLOSED


# ── Pre-configured Breakers ──────────────────────────────────────────────────


class TestPreconfiguredBreakers:
    def test_resy_breaker_exists(self):
        assert resy_breaker.name == "resy"
        assert resy_breaker.fail_max == 5

    def test_google_places_breaker_exists(self):
        assert google_places_breaker.name == "google_places"

    def test_opentable_breaker_exists(self):
        assert opentable_breaker.name == "opentable"

    def test_weather_breaker_exists(self):
        assert weather_breaker.name == "weather"
        assert weather_breaker.fail_max == 3
        assert weather_breaker.reset_timeout == 120.0


# ── Schema Validation ────────────────────────────────────────────────────────


class TestSchemaValidation:
    def test_valid_availability_passes(self):
        validate_resy_availability_schema({"results": []})

    def test_missing_key_raises_schema_change(self):
        with pytest.raises(SchemaChangeError, match="results"):
            validate_resy_availability_schema({})

    def test_non_dict_raises_schema_change(self):
        with pytest.raises(SchemaChangeError, match="Expected dict"):
            validate_resy_availability_schema("not a dict")  # type: ignore[arg-type]

    def test_valid_details_passes(self):
        validate_resy_details_schema({"book_token": {"value": "abc"}})

    def test_missing_details_key_raises(self):
        with pytest.raises(SchemaChangeError, match="book_token"):
            validate_resy_details_schema({})

    def test_details_non_dict_raises(self):
        with pytest.raises(SchemaChangeError, match="Expected dict"):
            validate_resy_details_schema([])  # type: ignore[arg-type]
