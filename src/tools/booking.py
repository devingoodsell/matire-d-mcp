"""MCP tools for booking: credentials, availability, reservations (Resy + OpenTable)."""

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


def register_booking_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Register booking management tools on the MCP server."""

    # ── Credential storage ─────────────────────────────────────────────

    @mcp.tool
    async def store_resy_credentials(
        email: str,
        password: str,
    ) -> str:
        """Save your Resy account credentials for automated booking.
        Credentials are encrypted and stored locally — never sent
        anywhere except to Resy's own servers for authentication.

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
    async def store_opentable_credentials(
        email: str,
        password: str,
    ) -> str:
        """Save your OpenTable account credentials for automated booking.
        Credentials are encrypted and stored locally.

        After saving, the system will verify the credentials work
        by attempting a test login.

        Args:
            email: Your OpenTable account email.
            password: Your OpenTable account password.

        Returns:
            Confirmation that credentials were saved and verified.
        """
        from src.clients.opentable import OpenTableClient
        from src.clients.resy_auth import AuthError

        store = _get_credential_store()

        # Save first so the client can read them during login
        store.save_credentials("opentable", {
            "email": email, "password": password
        })

        # Verify by attempting login
        ot_client = OpenTableClient(credential_store=store)
        try:
            await ot_client._login()  # noqa: SLF001
            return "OpenTable credentials saved and verified."
        except AuthError as exc:
            return f"Credentials saved but login verification failed: {exc}"
        finally:
            await ot_client.close()

    # ── Availability ───────────────────────────────────────────────────

    @mcp.tool
    async def check_availability(
        restaurant_name: str,
        date: str,
        party_size: int = 2,
        preferred_time: str | None = None,
    ) -> str:
        """Check reservation availability at a restaurant.
        Searches both Resy and OpenTable when available.

        Args:
            restaurant_name: Name of the restaurant.
            date: Date to check — "2026-02-14", "Saturday", "tomorrow", etc.
            party_size: Number of diners.
            preferred_time: Preferred time like "19:00". Results are sorted
                           by proximity to this time if provided.

        Returns:
            Available time slots with platform info, or a message if none found.
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
            return (
                f"Could not parse date '{date}'. "
                "Try YYYY-MM-DD, 'tomorrow', or a day name."
            )

        # Find restaurant in cache
        cached = await db.search_cached_restaurants(restaurant_name)
        if not cached:
            return (
                f"Restaurant '{restaurant_name}' not found in cache. "
                "Search for it first with search_restaurants."
            )
        restaurant = cached[0]

        all_slots = []

        # ── Check Resy ──
        store = _get_credential_store()
        resy_creds = store.get_credentials("resy")
        venue_id = restaurant.resy_venue_id

        if resy_creds:
            auth_mgr = _get_auth_manager()
            try:
                token = await auth_mgr.ensure_valid_token()
                api_key = resy_creds.get("api_key", "")
                resy_client = ResyClient(api_key=api_key, auth_token=token)

                if not venue_id:
                    matcher = VenueMatcher(db=db, resy_client=resy_client)
                    venue_id = await matcher.find_resy_venue(restaurant)

                if venue_id:
                    resy_slots = await resy_client.find_availability(
                        venue_id=venue_id, date=parsed_date, party_size=party_size,
                    )
                    all_slots.extend(resy_slots)
            except AuthError:
                logger.warning("Resy auth failed during availability check")

        # ── Check OpenTable ──
        ot_slug = restaurant.opentable_id
        if not ot_slug:
            matcher = VenueMatcher(db=db)
            ot_slug = await matcher.find_opentable_slug(restaurant)

        if ot_slug:
            from src.clients.opentable import OpenTableClient

            ot_client = OpenTableClient(credential_store=store)
            try:
                ot_slots = await ot_client.find_availability(
                    restaurant_slug=ot_slug,
                    date=parsed_date,
                    party_size=party_size,
                    preferred_time=preferred_time or "19:00",
                )
                all_slots.extend(ot_slots)
            finally:
                await ot_client.close()

        if not all_slots:
            return (
                f"No availability at {restaurant.name} on {parsed_date} "
                f"for {party_size} guests."
            )

        # Sort by proximity to preferred time if provided
        if preferred_time:
            all_slots.sort(key=lambda s: abs(_time_diff(s.time, preferred_time)))

        # Format
        lines = [f"{restaurant.name} — {parsed_date}, party of {party_size}:"]
        for slot in all_slots:
            type_label = f" - {slot.type}" if slot.type else ""
            platform_label = slot.platform.value.capitalize()
            lines.append(
                f"  {_format_time(slot.time)}{type_label} ({platform_label})"
            )
        return "\n".join(lines)

    # ── Booking ────────────────────────────────────────────────────────

    @mcp.tool
    async def make_reservation(
        restaurant_name: str,
        date: str,
        time: str,
        party_size: int = 2,
        special_requests: str | None = None,
    ) -> str:
        """Book a reservation at a restaurant via Resy or OpenTable.
        Only call this after the user has confirmed they want to book.

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
        from src.matching.venue_matcher import (
            VenueMatcher,
            generate_opentable_deep_link,
            generate_resy_deep_link,
        )
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

        normalised_time = _normalise_time(time)
        store = _get_credential_store()

        # ── Try Resy first ──
        resy_creds = store.get_credentials("resy")
        venue_id = restaurant.resy_venue_id

        if resy_creds:
            auth_mgr = _get_auth_manager()
            try:
                token = await auth_mgr.ensure_valid_token()
                api_key = resy_creds.get("api_key", "")
                resy_client = ResyClient(api_key=api_key, auth_token=token)

                if not venue_id:
                    matcher = VenueMatcher(db=db, resy_client=resy_client)
                    venue_id = await matcher.find_resy_venue(restaurant)

                if venue_id:
                    result = await _book_via_resy(
                        resy_client, db, restaurant, venue_id,
                        parsed_date, normalised_time, party_size,
                        special_requests, resy_creds,
                    )
                    if result:
                        return result
            except AuthError:
                logger.warning("Resy auth failed during booking")

        # ── Try OpenTable ──
        ot_slug = restaurant.opentable_id
        if not ot_slug:
            matcher = VenueMatcher(db=db)
            ot_slug = await matcher.find_opentable_slug(restaurant)

        if ot_slug:
            from src.clients.opentable import OpenTableClient

            ot_client = OpenTableClient(credential_store=store)
            try:
                result = await ot_client.book(
                    restaurant_slug=ot_slug,
                    date=parsed_date,
                    time=normalised_time,
                    party_size=party_size,
                    special_requests=special_requests,
                )
                if "error" not in result:
                    conf = result.get("confirmation_number", "")
                    reservation = Reservation(
                        restaurant_id=restaurant.id,
                        restaurant_name=restaurant.name,
                        platform=BookingPlatform.OPENTABLE,
                        platform_confirmation_id=str(conf),
                        date=parsed_date,
                        time=normalised_time,
                        party_size=party_size,
                        special_requests=special_requests,
                    )
                    await db.save_reservation(reservation)
                    return (
                        f"Booked! {restaurant.name}, {parsed_date} at "
                        f"{_format_time(normalised_time)}, party of {party_size}.\n"
                        f"Confirmation: {conf} (OpenTable)"
                    )
            finally:
                await ot_client.close()

        # ── Fallback: deep links ──
        links: list[str] = []
        if venue_id:
            links.append(
                generate_resy_deep_link(venue_id, parsed_date, party_size)
            )
        if ot_slug:
            links.append(
                generate_opentable_deep_link(
                    ot_slug, parsed_date, normalised_time, party_size
                )
            )
        if links:
            link_text = "\n".join(links)
            return (
                f"Could not complete booking automatically for {restaurant.name}.\n"
                f"Try booking directly:\n{link_text}"
            )
        return (
            f"'{restaurant.name}' doesn't appear to be on Resy or OpenTable."
        )

    # ── Cancellation ───────────────────────────────────────────────────

    @mcp.tool
    async def cancel_reservation(
        restaurant_name: str | None = None,
        confirmation_id: str | None = None,
    ) -> str:
        """Cancel an existing reservation (Resy or OpenTable).

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
        from src.models.enums import BookingPlatform

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
                if (
                    restaurant_name
                    and restaurant_name.lower() in r.restaurant_name.lower()
                ):
                    res = r
                    break

        if not res:
            return "No matching reservation found."

        store = _get_credential_store()

        # Route cancellation by platform
        if res.platform == BookingPlatform.OPENTABLE:
            from src.clients.opentable import OpenTableClient

            ot_client = OpenTableClient(credential_store=store)
            try:
                conf_id = res.platform_confirmation_id or res.id or ""
                success = await ot_client.cancel(conf_id)
            finally:
                await ot_client.close()

            if not success:
                return f"Failed to cancel OpenTable reservation at {res.restaurant_name}."
            await db.cancel_reservation(res.id or "")
            return f"Cancelled reservation at {res.restaurant_name} on {res.date}."

        # Default: Resy
        auth_mgr = _get_auth_manager()
        try:
            token = await auth_mgr.ensure_valid_token()
        except AuthError as exc:
            return f"Resy auth error: {exc}"

        resy_creds = store.get_credentials("resy") or {}
        api_key = resy_creds.get("api_key", "")

        resy_client = ResyClient(api_key=api_key, auth_token=token)
        resy_token = res.platform_confirmation_id or res.id or ""
        success = await resy_client.cancel(resy_token)

        if not success:
            return f"Failed to cancel reservation at {res.restaurant_name}."

        await db.cancel_reservation(res.id or "")
        return f"Cancelled reservation at {res.restaurant_name} on {res.date}."

    # ── View reservations ──────────────────────────────────────────────

    @mcp.tool
    async def my_reservations() -> str:
        """Show all your upcoming reservations across Resy and OpenTable.

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


# ── Private helpers ────────────────────────────────────────────────────


async def _book_via_resy(
    resy_client: object,
    db: object,
    restaurant: object,
    venue_id: str,
    parsed_date: str,
    normalised_time: str,
    party_size: int,
    special_requests: str | None,
    creds: dict,
) -> str | None:
    """Attempt to book via Resy. Returns confirmation string or None on failure."""
    from src.models.enums import BookingPlatform
    from src.models.reservation import Reservation

    slots = await resy_client.find_availability(  # type: ignore[union-attr]
        venue_id=venue_id, date=parsed_date, party_size=party_size
    )
    matching = [s for s in slots if s.time == normalised_time]
    if not matching:
        return None

    slot = matching[0]

    details = await resy_client.get_booking_details(  # type: ignore[union-attr]
        config_id=slot.config_id or "",
        date=parsed_date,
        party_size=party_size,
    )
    book_token = details.get("book_token", {}).get("value", "")
    if not book_token:
        return None

    payment = creds.get("payment_methods")
    payment_dict = (
        {"id": payment} if isinstance(payment, (str, int)) else None
    )
    result = await resy_client.book(  # type: ignore[union-attr]
        book_token=book_token, payment_method=payment_dict
    )
    if "error" in result:
        return None

    confirmation_id = result.get("resy_token", result.get("reservation_id", ""))
    reservation = Reservation(
        restaurant_id=restaurant.id,  # type: ignore[union-attr]
        restaurant_name=restaurant.name,  # type: ignore[union-attr]
        platform=BookingPlatform.RESY,
        platform_confirmation_id=str(confirmation_id),
        date=parsed_date,
        time=normalised_time,
        party_size=party_size,
        special_requests=special_requests,
    )
    await db.save_reservation(reservation)  # type: ignore[union-attr]

    return (
        f"Booked! {restaurant.name}, {parsed_date} at "  # type: ignore[union-attr]
        f"{_format_time(normalised_time)}, party of {party_size}.\n"
        f"Confirmation: {confirmation_id}"
    )


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
