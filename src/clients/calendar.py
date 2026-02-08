"""Google Calendar link generation for restaurant reservations."""

from urllib.parse import quote


def generate_gcal_link(
    restaurant_name: str,
    restaurant_address: str,
    date: str,
    time: str,
    party_size: int,
    confirmation_id: str | None = None,
    platform: str | None = None,
) -> str:
    """Generate a Google Calendar event URL for a reservation.

    Args:
        restaurant_name: Name of the restaurant.
        restaurant_address: Full address.
        date: Date in YYYY-MM-DD format.
        time: Time in HH:MM 24-hour format.
        party_size: Number of diners.
        confirmation_id: Optional booking confirmation ID.
        platform: Optional booking platform name (e.g. "Resy").

    Returns:
        A Google Calendar URL string.
    """
    # Format dates as YYYYMMDDTHHmmSS (local time, no timezone)
    date_clean = date.replace("-", "")
    time_clean = time.replace(":", "")
    start = f"{date_clean}T{time_clean}00"

    # Assume 2-hour dinner
    hour = int(time[:2])
    minute = int(time[3:5])
    end_hour = hour + 2
    end = f"{date_clean}T{end_hour:02d}{minute:02d}00"

    title = f"Dinner at {restaurant_name}"

    # Build description
    details_parts = [f"Party of {party_size}"]
    if confirmation_id:
        details_parts.append(f"Confirmation: {confirmation_id}")
    if platform:
        details_parts.append(f"Booked via {platform}")
    details = "\n".join(details_parts)

    params = (
        f"action=TEMPLATE"
        f"&text={quote(title)}"
        f"&dates={start}/{end}"
        f"&location={quote(restaurant_address)}"
        f"&details={quote(details)}"
    )
    return f"https://calendar.google.com/calendar/render?{params}"
