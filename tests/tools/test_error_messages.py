"""Tests for src.tools.error_messages — get_user_message + safe_tool_wrapper."""

from src.clients.resilience import (
    AuthError,
    CAPTCHAError,
    CircuitOpenError,
    PermanentAPIError,
    SchemaChangeError,
    TransientAPIError,
)
from src.tools.error_messages import get_user_message, safe_tool_wrapper


class TestGetUserMessage:
    def test_auth_error(self):
        msg = get_user_message(AuthError("token expired"))
        assert "credentials" in msg.lower()

    def test_captcha_error(self):
        msg = get_user_message(CAPTCHAError("captcha"))
        assert "CAPTCHA" in msg

    def test_schema_change_error(self):
        msg = get_user_message(SchemaChangeError("missing key"))
        assert "changed" in msg.lower()

    def test_circuit_open_error(self):
        msg = get_user_message(CircuitOpenError("resy"))
        assert "temporarily unavailable" in msg

    def test_circuit_open_with_context(self):
        msg = get_user_message(
            CircuitOpenError("resy"),
            context={"restaurant": "Carbone"},
        )
        assert "Carbone" in msg

    def test_transient_error(self):
        msg = get_user_message(TransientAPIError("503"))
        assert "temporary" in msg.lower()

    def test_transient_with_context(self):
        msg = get_user_message(
            TransientAPIError("503"),
            context={"restaurant": "Lilia"},
        )
        assert "Lilia" in msg

    def test_permanent_error(self):
        msg = get_user_message(PermanentAPIError("not found"))
        assert "not found" in msg.lower()

    def test_unknown_error(self):
        msg = get_user_message(ValueError("unexpected"))
        assert "something went wrong" in msg.lower()

    def test_no_context_uses_default(self):
        msg = get_user_message(CircuitOpenError("test"))
        assert "the restaurant" in msg


class TestSafeToolWrapper:
    async def test_success_returns_result(self):
        async def good_func():
            return "success"

        result = await safe_tool_wrapper(good_func)
        assert result == "success"

    async def test_failure_returns_friendly_message(self):
        async def bad_func():
            raise AuthError("expired")

        result = await safe_tool_wrapper(bad_func)
        assert "credentials" in result.lower()

    async def test_passes_args_and_kwargs(self):
        async def adder(a, b, prefix=""):
            return f"{prefix}{a + b}"

        result = await safe_tool_wrapper(adder, 1, 2, prefix="sum=")
        assert result == "sum=3"

    async def test_context_passed_to_error(self):
        async def fail():
            raise TransientAPIError("500")

        result = await safe_tool_wrapper(
            fail, context={"restaurant": "Lilia"}
        )
        assert "Lilia" in result

    async def test_unknown_exception_handled(self):
        async def fail():
            raise RuntimeError("oops")

        result = await safe_tool_wrapper(fail)
        assert "something went wrong" in result.lower()
