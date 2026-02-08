"""User-friendly error messages and safe tool wrapper."""

import logging

from src.clients.resilience import (
    AuthError,
    CAPTCHAError,
    CircuitOpenError,
    PermanentAPIError,
    SchemaChangeError,
    TransientAPIError,
)

logger = logging.getLogger(__name__)


def get_user_message(error: Exception, context: dict | None = None) -> str:
    """Map an exception to a user-friendly message.

    Args:
        error: The exception to translate.
        context: Optional dict with extra info (e.g. {"restaurant": "Carbone"}).

    Returns:
        A human-readable error message.
    """
    restaurant = (context or {}).get("restaurant", "the restaurant")

    if isinstance(error, AuthError):
        return (
            "Your login credentials have expired or are invalid. "
            "Please re-enter them with the store credentials tool."
        )
    if isinstance(error, CAPTCHAError):
        return (
            "The booking site is asking for a CAPTCHA verification. "
            "Please try booking directly on their website."
        )
    if isinstance(error, SchemaChangeError):
        return (
            "The booking platform changed its interface. "
            "This feature may need an update — please try again later."
        )
    if isinstance(error, CircuitOpenError):
        return (
            f"The service for {restaurant} is temporarily unavailable. "
            "Please try again in a few minutes."
        )
    if isinstance(error, TransientAPIError):
        return (
            f"There was a temporary issue reaching {restaurant}'s booking service. "
            "Please try again shortly."
        )
    if isinstance(error, PermanentAPIError):
        return f"Could not complete the request for {restaurant}. {error}"
    return "Something went wrong. Please try again or contact support."


async def safe_tool_wrapper(
    func,  # type: ignore[no-untyped-def]
    *args: object,
    context: dict | None = None,
    **kwargs: object,
) -> str:
    """Call an async function, catching errors and returning friendly messages.

    Args:
        func: Async callable to invoke.
        *args: Positional arguments for *func*.
        context: Optional context dict for error messages.
        **kwargs: Keyword arguments for *func*.

    Returns:
        The function's return value on success, or a user-friendly error string.
    """
    try:
        return await func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool error in %s", func.__name__)
        return get_user_message(exc, context)
