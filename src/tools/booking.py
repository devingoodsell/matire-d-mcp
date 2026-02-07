"""MCP tools for Resy booking: credentials, availability, reservations."""

import logging

from fastmcp import FastMCP

from src.server import get_db

logger = logging.getLogger(__name__)


def _get_credential_store() -> "CredentialStore":  # noqa: F821
    """Build a CredentialStore from settings."""
    from src.config import get_settings
    from src.storage.credentials import CredentialStore

    settings = get_settings()
    return CredentialStore(settings.credentials_path)


def _get_auth_manager() -> "ResyAuthManager":  # noqa: F821
    """Build a ResyAuthManager backed by the credential store."""
    from src.clients.resy_auth import ResyAuthManager

    return ResyAuthManager(_get_credential_store())


def register_booking_tools(mcp: FastMCP) -> None:
    """Register booking management tools on the MCP server."""

    @mcp.tool
    async def store_resy_credentials(
        email: str,
        password: str,
    ) -> str:
        """Save your Resy account credentials for automated booking.
        Credentials are encrypted and stored locally — never sent
        anywhere except to Resy's own servers for authentication.

        After saving, the system will attempt to log in and verify the
        credentials work.

        Args:
            email: Your Resy account email.
            password: Your Resy account password.

        Returns:
            Confirmation that credentials were saved and verified,
            or an error if login failed.
        """
        from src.clients.resy_auth import AuthError

        store = _get_credential_store()
        auth_mgr = _get_auth_manager()

        try:
            result = await auth_mgr.authenticate(email, password)
        except (AuthError, Exception) as exc:  # noqa: BLE001
            return f"Login failed: {exc}"

        creds = {
            "email": email,
            "password": password,
            "auth_token": result["auth_token"],
            "api_key": result["api_key"],
            "payment_methods": result.get("payment_methods", []),
        }
        store.save_credentials("resy", creds)

        payment_info = result.get("payment_methods")
        if payment_info:
            return "Credentials saved and verified. Payment method detected."
        return "Credentials saved and verified."

    @mcp.tool
    async def check_availability(
        restaurant_name: str,
        date: str,
        party_size: int = 2,
        preferred_time: str | None = None,
    ) -> str:
        """Check reservation availability at a restaurant on Resy.

        Args:
            restaurant_name: Name of the restaurant.
            date: Date to check — "2026-02-14", "Saturday", "tomorrow", etc.
            party_size: Number of diners.
            preferred_time: Preferred time like "19:00". Results are sorted
                           by proximity to this time if provided.

        Returns:
            Available time slots, or a message if none found.
        """
        from src.clients.resy import ResyClient
        from src.clients.resy_auth import AuthError
        from src.matching.venue_matcher import VenueMatcher
        from src.tools.date_utils import parse_date

        db = get_db()

        # Parse date
        try:
            parsed_date = parse_date(date)
        except ValueError:
            return f"Could not parse date '{date}'. Try YYYY-MM-DD, 'tomorrow', or a day name."

        # Find restaurant in cache
        cached = await db.search_cached_restaurants(restaurant_name)
        if not cached:
            return (
                f"Restaurant '{restaurant_name}' not found in cache. "
                "Search for it first with search_restaurants."
            )
        restaurant = cached[0]

        # Get auth token
        auth_mgr = _get_auth_manager()
        try:
            token = await auth_mgr.ensure_valid_token()
        except AuthError as exc:
            return f"Resy auth error: {exc}"

        store = _get_credential_store()
        creds = store.get_credentials("resy") or {}
        api_key = creds.get("api_key", "")

        resy_client = ResyClient(api_key=api_key, auth_token=token)

        # Find venue ID
        venue_id = restaurant.resy_venue_id
        if not venue_id:
            matcher = VenueMatcher(db=db, resy_client=resy_client)
            venue_id = await matcher.find_resy_venue(restaurant)

        if not venue_id:
            return f"'{restaurant.name}' doesn't appear to be on Resy."

        # Get availability
        slots = await resy_client.find_availability(
            venue_id=venue_id,
            date=parsed_date,
            party_size=party_size,
        )

        if not slots:
            return (
                f"No availability at {restaurant.name} on {parsed_date} "
                f"for {party_size} guests."
            )

        # Sort by proximity to preferred time if provided
        if preferred_time:
            slots.sort(key=lambda s: abs(_time_diff(s.time, preferred_time)))

        # Format
        lines = [f"{restaurant.name} — {parsed_date}, party of {party_size}:"]
        for slot in slots:
            type_label = f" - {slot.type}" if slot.type else ""
            lines.append(f"  {_format_time(slot.time)}{type_label} (Resy)")
        return "\n".join(lines)

    @mcp.tool
    async def make_reservation(
        restaurant_name: str,
        date: str,
        time: str,
        party_size: int = 2,
        special_requests: str | None = None,
    ) -> str:
        """Book a reservation at a restaurant via Resy. Only call this
        after the user has confirmed they want to book.

        Args:
            restaurant_name: Name of the restaurant.
            date: Reservation date — "2026-02-14", "Saturday", etc.
            time: Reservation time — "19:00" or "7:00 PM".
            party_size: Number of diners.
            special_requests: E.g. "birthday", "quiet table".

        Returns:
            Confirmation with details and confirmation number.
        """
        from src.clients.resy import ResyClient
        from src.clients.resy_auth import AuthError
        from src.matching.venue_matcher import VenueMatcher
        from src.models.enums import BookingPlatform
        from src.models.reservation import Reservation
        from src.tools.date_utils import parse_date

        db = get_db()

        try:
            parsed_date = parse_date(date)
        except ValueError:
            return f"Could not parse date '{date}'."

        # Find restaurant
        cached = await db.search_cached_restaurants(restaurant_name)
        if not cached:
            return f"Restaurant '{restaurant_name}' not found. Search for it first."
        restaurant = cached[0]

        # Auth
        auth_mgr = _get_auth_manager()
        try:
            token = await auth_mgr.ensure_valid_token()
        except AuthError as exc:
            return f"Resy auth error: {exc}"

        store = _get_credential_store()
        creds = store.get_credentials("resy") or {}
        api_key = creds.get("api_key", "")

        resy_client = ResyClient(api_key=api_key, auth_token=token)

        # Find venue ID
        venue_id = restaurant.resy_venue_id
        if not venue_id:
            matcher = VenueMatcher(db=db, resy_client=resy_client)
            venue_id = await matcher.find_resy_venue(restaurant)
        if not venue_id:
            return f"'{restaurant.name}' doesn't appear to be on Resy."

        # Find matching slot
        slots = await resy_client.find_availability(
            venue_id=venue_id, date=parsed_date, party_size=party_size
        )
        normalised_time = _normalise_time(time)
        matching = [s for s in slots if s.time == normalised_time]
        if not matching:
            available = ", ".join(_format_time(s.time) for s in slots[:5])
            return (
                f"No slot at {_format_time(normalised_time)} on {parsed_date}. "
                f"Available: {available}" if available
                else f"No availability at {restaurant.name} on {parsed_date}."
            )

        slot = matching[0]

        # Get booking details
        details = await resy_client.get_booking_details(
            config_id=slot.config_id or "",
            date=parsed_date,
            party_size=party_size,
        )
        book_token = details.get("book_token", {}).get("value", "")
        if not book_token:
            return "Could not get booking token. The slot may no longer be available."

        # Book it
        payment = creds.get("payment_methods")
        payment_dict = (
            {"id": payment} if isinstance(payment, (str, int)) else None
        )
        result = await resy_client.book(
            book_token=book_token, payment_method=payment_dict
        )
        if "error" in result:
            return f"Booking failed: {result['error']}"

        # Save locally
        confirmation_id = result.get("resy_token", result.get("reservation_id", ""))
        reservation = Reservation(
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            platform=BookingPlatform.RESY,
            platform_confirmation_id=str(confirmation_id),
            date=parsed_date,
            time=normalised_time,
            party_size=party_size,
            special_requests=special_requests,
        )
        await db.save_reservation(reservation)

        return (
            f"Booked! {restaurant.name}, {parsed_date} at "
            f"{_format_time(normalised_time)}, party of {party_size}.\n"
            f"Confirmation: {confirmation_id}"
        )

    @mcp.tool
    async def cancel_reservation(
        restaurant_name: str | None = None,
        confirmation_id: str | None = None,
    ) -> str:
        """Cancel an existing Resy reservation.

        Provide either the restaurant name (cancels most recent upcoming)
        or a specific confirmation ID.

        Args:
            restaurant_name: Restaurant name to look up.
            confirmation_id: Specific confirmation ID.

        Returns:
            Cancellation confirmation or error.
        """
        from src.clients.resy import ResyClient
        from src.clients.resy_auth import AuthError

        db = get_db()

        if not restaurant_name and not confirmation_id:
            return "Provide either restaurant_name or confirmation_id."

        # Find the reservation
        if confirmation_id:
            res = await db.get_reservation(confirmation_id)
        else:
            upcoming = await db.get_upcoming_reservations()
            res = None
            for r in upcoming:
                if restaurant_name and restaurant_name.lower() in r.restaurant_name.lower():
                    res = r
                    break

        if not res:
            return "No matching reservation found."

        # Cancel via Resy
        auth_mgr = _get_auth_manager()
        try:
            token = await auth_mgr.ensure_valid_token()
        except AuthError as exc:
            return f"Resy auth error: {exc}"

        store = _get_credential_store()
        creds = store.get_credentials("resy") or {}
        api_key = creds.get("api_key", "")

        resy_client = ResyClient(api_key=api_key, auth_token=token)
        resy_token = res.platform_confirmation_id or res.id or ""
        success = await resy_client.cancel(resy_token)

        if not success:
            return f"Failed to cancel reservation at {res.restaurant_name}."

        await db.cancel_reservation(res.id or "")
        return f"Cancelled reservation at {res.restaurant_name} on {res.date}."

    @mcp.tool
    async def my_reservations() -> str:
        """Show all your upcoming reservations.

        Returns:
            Formatted list of upcoming reservations with dates,
            times, party sizes, and confirmation numbers.
        """
        db = get_db()
        upcoming = await db.get_upcoming_reservations()

        if not upcoming:
            return "No upcoming reservations."

        lines: list[str] = ["Your upcoming reservations:"]
        for r in upcoming:
            time_str = _format_time(r.time)
            lines.append(
                f"  {r.restaurant_name} — {r.date} at {time_str}, "
                f"party of {r.party_size} ({r.platform.value})"
            )
            if r.platform_confirmation_id:
                lines.append(f"    Confirmation: {r.platform_confirmation_id}")
        return "\n".join(lines)


def _format_time(time_24: str) -> str:
    """Convert 24-hour time string to 12-hour display format."""
    try:
        parts = time_24.split(":")
        hour = int(parts[0])
        minute = parts[1] if len(parts) > 1 else "00"
        suffix = "AM" if hour < 12 else "PM"
        display_hour = hour % 12 or 12
        return f"{display_hour}:{minute} {suffix}"
    except (ValueError, IndexError):
        return time_24


def _normalise_time(time_str: str) -> str:
    """Normalise time input to HH:MM 24-hour format."""
    time_str = time_str.strip().upper()

    # Already 24-hour
    if ":" in time_str and "AM" not in time_str and "PM" not in time_str:
        return time_str

    # 12-hour with AM/PM
    is_pm = "PM" in time_str
    time_str = time_str.replace("AM", "").replace("PM", "").strip()
    parts = time_str.split(":")
    hour = int(parts[0])
    minute = parts[1] if len(parts) > 1 else "00"

    if is_pm and hour != 12:
        hour += 12
    elif not is_pm and hour == 12:
        hour = 0

    return f"{hour:02d}:{minute}"


def _time_diff(time_a: str, time_b: str) -> int:
    """Compute absolute difference in minutes between two HH:MM strings."""
    try:
        a_parts = time_a.split(":")
        b_parts = time_b.split(":")
        a_min = int(a_parts[0]) * 60 + int(a_parts[1])
        b_min = int(b_parts[0]) * 60 + int(b_parts[1])
        return abs(a_min - b_min)
    except (ValueError, IndexError):
        return 9999
