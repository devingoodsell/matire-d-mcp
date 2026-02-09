"""MCP tools for booking: credentials, availability, reservations (Resy + OpenTable)."""

import logging

from fastmcp import FastMCP

from src.server import get_db, resolve_credential

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


async def _ensure_resy_credentials() -> dict | None:
    """Get Resy credentials, auto-authenticating from ConfigStore if needed."""
    store = _get_credential_store()
    creds = store.get_credentials("resy")
    if creds:
        return creds

    # Master-key mode: try to auto-authenticate from ConfigStore
    from src.clients.resy_auth import AuthError

    email = await resolve_credential("resy_email")
    password = await resolve_credential("resy_password")
    if not email or not password:
        return None

    auth_mgr = _get_auth_manager()
    try:
        result = await auth_mgr.authenticate(email, password)
    except (AuthError, Exception):  # noqa: BLE001
        logger.warning("Resy auto-auth from ConfigStore failed")
        return None

    creds = {
        "email": email,
        "auth_token": result["auth_token"],
        "api_key": result["api_key"],
        "payment_methods": result.get("payment_methods", []),
    }
    store.save_credentials("resy", creds)
    return creds


async def _ensure_opentable_credentials() -> dict | None:
    """Get OpenTable credentials, resolving from ConfigStore/env vars if needed."""
    store = _get_credential_store()
    creds = store.get_credentials("opentable")
    if creds:
        return creds

    # Master-key mode: resolve from ConfigStore / env vars
    csrf_token = await resolve_credential("opentable_csrf_token")
    email = await resolve_credential("opentable_email")
    if not csrf_token:
        return None

    creds: dict = {"csrf_token": csrf_token, "email": email or ""}
    cookies = await resolve_credential("opentable_cookies")
    if cookies:
        creds["cookies"] = cookies
    store.save_credentials("opentable", creds)
    return creds


def register_booking_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Register booking management tools on the MCP server."""

    # ── Credential storage ─────────────────────────────────────────────

    @mcp.tool
    async def store_resy_credentials(
        email: str | None = None,
        password: str | None = None,
    ) -> str:
        """Save your Resy account credentials for automated booking.

        **Recommended:** Set RESY_EMAIL and RESY_PASSWORD as environment
        variables (or in your .env file) so credentials never appear in chat
        history. If env vars are set, call this tool with no arguments.

        Credentials are encrypted and stored locally — never sent
        anywhere except to Resy's own servers for authentication.
        The password is NOT persisted after authentication.

        Args:
            email: Your Resy account email (or set RESY_EMAIL env var).
            password: Your Resy account password (or set RESY_PASSWORD env var).

        Returns:
            Confirmation that credentials were saved and verified,
            or an error if login failed.
        """
        from src.clients.resy_auth import AuthError

        email = email or await resolve_credential("resy_email")
        password = password or await resolve_credential("resy_password")
        if not email or not password:
            return (
                "Missing credentials. Set RESY_EMAIL and RESY_PASSWORD env vars, "
                "or pass them as arguments."
            )

        store = _get_credential_store()
        auth_mgr = _get_auth_manager()

        try:
            result = await auth_mgr.authenticate(email, password)
        except (AuthError, Exception) as exc:  # noqa: BLE001
            return f"Login failed: {exc}"

        creds = {
            "email": email,
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
        csrf_token: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
    ) -> str:
        """Save your OpenTable DAPI credentials for automated booking.

        The CSRF token (``x-csrf-token``) is required for booking. To get it:
        1. Log into opentable.com in your browser
        2. Open DevTools → Network tab
        3. Make any action (search, etc.)
        4. Find any request to ``/dapi/`` and copy the ``x-csrf-token`` header value

        **Recommended:** Set OPENTABLE_CSRF_TOKEN as an environment variable
        so it never appears in chat history.

        Args:
            csrf_token: The x-csrf-token value from your browser session
                        (or set OPENTABLE_CSRF_TOKEN env var).
            email: Your OpenTable account email (or set OPENTABLE_EMAIL env var).
            first_name: First name for reservations.
            last_name: Last name for reservations.
            phone: Phone number for reservations.

        Returns:
            Confirmation that credentials were saved.
        """
        csrf_token = csrf_token or await resolve_credential("opentable_csrf_token")
        email = email or await resolve_credential("opentable_email")
        if not csrf_token:
            return (
                "Missing CSRF token. Set OPENTABLE_CSRF_TOKEN env var, "
                "or pass csrf_token as an argument. "
                "Get it from browser DevTools → Network → any /dapi/ request → x-csrf-token header."
            )

        store = _get_credential_store()
        creds: dict = {"csrf_token": csrf_token, "email": email or ""}
        if first_name:
            creds["first_name"] = first_name
        if last_name:
            creds["last_name"] = last_name
        if phone:
            creds["phone"] = phone

        store.save_credentials("opentable", creds)
        return "OpenTable credentials saved."

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
        resy_creds = await _ensure_resy_credentials()
        venue_id = restaurant.resy_venue_id

        if resy_creds:
            auth_mgr = _get_auth_manager()
            try:
                token = await auth_mgr.ensure_valid_token()
                api_key = resy_creds.get("api_key", "")
                resy_client = ResyClient(api_key=api_key, auth_token=token)

                if venue_id is None:
                    matcher = VenueMatcher(db=db, resy_client=resy_client)
                    venue_id = await matcher.find_resy_venue(restaurant)

                if venue_id:
                    resy_slots = await resy_client.find_availability(
                        venue_id=venue_id, date=parsed_date, party_size=party_size,
                    )
                    all_slots.extend(resy_slots)
            except AuthError:
                logger.warning("Resy auth failed during availability check")

        # ── Check OpenTable via DAPI ──
        ot_slug = restaurant.opentable_id
        if ot_slug is None:
            matcher = VenueMatcher(db=db)
            ot_slug = await matcher.find_opentable_slug(restaurant)

        if ot_slug:
            from src.clients.opentable import OpenTableClient

            store = _get_credential_store()
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

        if not all_slots and not ot_slug:
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
        if ot_slug:
            from src.matching.venue_matcher import generate_opentable_deep_link

            ot_link = generate_opentable_deep_link(
                ot_slug, parsed_date, preferred_time or "19:00", party_size,
            )
            lines.append(f"Also check OpenTable directly: {ot_link}")
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
        resy_creds = await _ensure_resy_credentials()

        # ── Try Resy first ──
        venue_id = restaurant.resy_venue_id
        resy_available_times: list[str] = []

        if resy_creds:
            auth_mgr = _get_auth_manager()
            try:
                token = await auth_mgr.ensure_valid_token()
                api_key = resy_creds.get("api_key", "")
                resy_client = ResyClient(api_key=api_key, auth_token=token)

                if venue_id is None:
                    matcher = VenueMatcher(db=db, resy_client=resy_client)
                    venue_id = await matcher.find_resy_venue(restaurant)

                if venue_id:
                    result, resy_available_times = await _book_via_resy(
                        resy_client, db, restaurant, venue_id,
                        parsed_date, normalised_time, party_size,
                        special_requests, resy_creds,
                    )
                    if result:
                        from src.clients.calendar import generate_gcal_link

                        cal_link = generate_gcal_link(
                            restaurant_name=restaurant.name,
                            restaurant_address=restaurant.address,
                            date=parsed_date,
                            time=normalised_time,
                            party_size=party_size,
                            platform="Resy",
                        )
                        return f"{result}\nAdd to calendar: {cal_link}"
            except AuthError:
                logger.warning("Resy auth failed during booking")

        # ── Try OpenTable DAPI ──
        ot_slug = restaurant.opentable_id
        if ot_slug is None:
            matcher = VenueMatcher(db=db)
            ot_slug = await matcher.find_opentable_slug(restaurant)

        if ot_slug:
            from src.clients.opentable import OpenTableClient
            from src.models.enums import BookingPlatform

            store = _get_credential_store()
            ot_client = OpenTableClient(credential_store=store)
            try:
                ot_slots = await ot_client.find_availability(
                    restaurant_slug=ot_slug,
                    date=parsed_date,
                    party_size=party_size,
                    preferred_time=normalised_time,
                )

                if ot_slots:
                    # Exact match?
                    exact = [s for s in ot_slots if s.time == normalised_time]
                    if exact:
                        slot = exact[0]
                        token, slot_hash = _split_config_id(slot.config_id)
                        book_result = await ot_client.book(
                            restaurant_slug=ot_slug,
                            date=parsed_date,
                            time=normalised_time,
                            party_size=party_size,
                            slot_availability_token=token,
                            slot_hash=slot_hash,
                        )
                        if "confirmation_number" in book_result:
                            from src.clients.calendar import generate_gcal_link
                            from src.models.reservation import Reservation

                            conf_id = book_result["confirmation_number"]
                            reservation = Reservation(
                                restaurant_id=restaurant.id,
                                restaurant_name=restaurant.name,
                                platform=BookingPlatform.OPENTABLE,
                                platform_confirmation_id=str(conf_id),
                                date=parsed_date,
                                time=normalised_time,
                                party_size=party_size,
                                special_requests=special_requests,
                            )
                            await db.save_reservation(reservation)

                            cal_link = generate_gcal_link(
                                restaurant_name=restaurant.name,
                                restaurant_address=restaurant.address,
                                date=parsed_date,
                                time=normalised_time,
                                party_size=party_size,
                                platform="OpenTable",
                            )
                            msg = (
                                f"Booked! {restaurant.name}, {parsed_date} at "
                                f"{_format_time(normalised_time)}, "
                                f"party of {party_size} (OpenTable).\n"
                                f"Confirmation: {conf_id}\n"
                                f"Add to calendar: {cal_link}"
                            )
                            return msg

                    # Proximity filter: ≤30min earlier OR ≤60min later
                    nearby = _filter_nearby_slots(ot_slots, normalised_time)
                    if nearby:
                        ot_link = generate_opentable_deep_link(
                            ot_slug, parsed_date, normalised_time, party_size,
                        )
                        nearby_times = ", ".join(
                            _format_time(s.time) for s in nearby
                        )
                        msg = (
                            f"{_format_time(normalised_time)} is not available "
                            f"at {restaurant.name} on OpenTable.\n"
                            f"Nearby times on OpenTable: {nearby_times}\n"
                            f"Book on OpenTable: {ot_link}"
                        )
                        if resy_available_times:
                            resy_formatted = ", ".join(
                                _format_time(t) for t in resy_available_times
                            )
                            msg += f"\nResy available times: {resy_formatted}"
                        return msg
            finally:
                await ot_client.close()

        # ── Fallback: deep links ──
        resy_link = None
        ot_link = None
        if venue_id:
            resy_link = generate_resy_deep_link(
                restaurant.name, parsed_date, party_size
            )
        if ot_slug:
            ot_link = generate_opentable_deep_link(
                ot_slug, parsed_date, normalised_time, party_size
            )
        if resy_link or ot_link:
            msg = (
                f"Not available at {restaurant.name} on {parsed_date} at "
                f"{_format_time(normalised_time)} on either Resy or OpenTable.\n"
            )
            if resy_available_times:
                formatted = ", ".join(
                    _format_time(t) for t in resy_available_times
                )
                msg += (
                    f"Resy available times: {formatted}\n"
                )
            if resy_link:
                msg += f"Try booking on Resy: {resy_link}\n"
            if ot_link:
                msg += f"Try booking on OpenTable: {ot_link}\n"
            if restaurant.website:
                msg += f"Restaurant website: {restaurant.website}"
            return msg.rstrip()
        msg = f"'{restaurant.name}' doesn't appear to be on Resy or OpenTable."
        if restaurant.website:
            msg += f"\nTry their website: {restaurant.website}"
        return msg

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
                # Resolve the numeric rid for the mobile API cancel
                rid: int | None = None
                cached = await db.get_cached_restaurant(res.restaurant_id)
                if cached and cached.opentable_id:
                    rid = await ot_client._resolve_restaurant_id(
                        cached.opentable_id,
                    )
                success = await ot_client.cancel(conf_id, rid=rid)
            finally:
                await ot_client.close()

            if not success:
                return f"Failed to cancel OpenTable reservation at {res.restaurant_name}."
            await db.cancel_reservation(res.id or "")
            return f"Cancelled reservation at {res.restaurant_name} on {res.date}."

        # Default: Resy
        resy_creds = await _ensure_resy_credentials()
        if not resy_creds:
            return "Resy credentials not available. Store them first."

        auth_mgr = _get_auth_manager()
        try:
            token = await auth_mgr.ensure_valid_token()
        except AuthError as exc:
            return f"Resy auth error: {exc}"

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
) -> tuple[str | None, list[str]]:
    """Attempt to book via Resy.

    Returns:
        Tuple of (confirmation_string_or_None, available_times).
        available_times is populated when slots exist but the requested
        time doesn't match, so the caller can inform the user.
    """
    from src.models.enums import BookingPlatform
    from src.models.reservation import Reservation

    slots = await resy_client.find_availability(  # type: ignore[union-attr]
        venue_id=venue_id, date=parsed_date, party_size=party_size
    )
    available = [s.time for s in slots]
    matching = [s for s in slots if s.time == normalised_time]
    if not matching:
        logger.warning(
            "Resy: no slot at %s for venue %s on %s (available: %s)",
            normalised_time, venue_id, parsed_date, available,
        )
        return None, available

    slot = matching[0]

    details = await resy_client.get_booking_details(  # type: ignore[union-attr]
        config_id=slot.config_id or "",
        date=parsed_date,
        party_size=party_size,
    )
    book_token = details.get("book_token", {}).get("value", "")
    if not book_token:
        logger.warning("Resy: no book_token returned for venue %s", venue_id)
        return None, available

    payment = creds.get("payment_methods")
    if isinstance(payment, list) and payment:
        payment_dict = payment[0] if isinstance(payment[0], dict) else {"id": payment[0]}
    elif isinstance(payment, (str, int)):
        payment_dict = {"id": payment}
    else:
        payment_dict = None
    result = await resy_client.book(  # type: ignore[union-attr]
        book_token=book_token, payment_method=payment_dict
    )
    if "error" in result:
        logger.warning("Resy: booking failed: %s", result["error"])
        return None, available

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
        f"Confirmation: {confirmation_id}",
        available,
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


def _time_diff_signed(slot_time: str, requested_time: str) -> int:
    """Signed difference: slot - requested, in minutes.

    Positive means slot is later, negative means slot is earlier.
    """
    try:
        s = slot_time.split(":")
        r = requested_time.split(":")
        return (int(s[0]) * 60 + int(s[1])) - (int(r[0]) * 60 + int(r[1]))
    except (ValueError, IndexError):
        return 9999


def _filter_nearby_slots(
    slots: list,
    requested_time: str,
) -> list:
    """Filter slots within the proximity window: ≤30min earlier OR ≤60min later.

    Excludes exact matches (diff == 0).
    """
    result = []
    for slot in slots:
        diff = _time_diff_signed(slot.time, requested_time)
        if diff == 0:
            continue
        if -30 <= diff <= 60:
            result.append(slot)
    return result


def _split_config_id(config_id: str | None) -> tuple[str, str]:
    """Split an OT config_id of the form 'token|hash' into (token, hash)."""
    if not config_id or "|" not in config_id:
        return ("", "")
    parts = config_id.split("|", 1)
    return (parts[0], parts[1])
