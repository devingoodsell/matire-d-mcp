"""Date parsing helpers for natural-language date strings."""

import re
from datetime import date, timedelta

# Day-of-week name → weekday int (Monday = 0)
_DAY_NAMES: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Month name/abbreviation → month int
_MONTH_NAMES: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_date(text: str, today: date | None = None) -> str:
    """Parse a natural-language date string into YYYY-MM-DD format.

    Supported formats:
    - "today", "tomorrow"
    - Day name: "Saturday", "this Saturday" (→ next occurrence)
    - "next Saturday" (→ the Saturday *after* this one)
    - "Feb 14", "February 14" (current or next year)
    - "2/14" (month/day)
    - ISO passthrough: "2026-02-14"

    Args:
        text: The date string to parse.
        today: Override for today's date (for testing).

    Returns:
        Date string in YYYY-MM-DD format.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    today = today or date.today()
    cleaned = text.strip().lower()

    # ISO passthrough
    if re.match(r"\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned

    # today / tomorrow
    if cleaned == "today":
        return today.isoformat()
    if cleaned == "tomorrow":
        return (today + timedelta(days=1)).isoformat()

    # "next <day>" — the occurrence *after* this week's
    next_match = re.match(r"next\s+(\w+)", cleaned)
    if next_match:
        day_name = next_match.group(1)
        if day_name in _DAY_NAMES:
            target_wd = _DAY_NAMES[day_name]
            days_ahead = (target_wd - today.weekday()) % 7
            # "next X" always means >= 7 days away
            if days_ahead == 0:
                days_ahead = 7
            days_ahead += 7  # skip to the *next* week
            return (today + timedelta(days=days_ahead)).isoformat()

    # "this <day>" or bare day name — next occurrence (including today)
    this_match = re.match(r"(?:this\s+)?(\w+)$", cleaned)
    if this_match:
        day_name = this_match.group(1)
        if day_name in _DAY_NAMES:
            target_wd = _DAY_NAMES[day_name]
            days_ahead = (target_wd - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).isoformat()

    # "Month Day" — e.g. "Feb 14", "February 14"
    month_day = re.match(r"([a-z]+)\s+(\d{1,2})$", cleaned)
    if month_day:
        month_str, day_str = month_day.group(1), month_day.group(2)
        if month_str in _MONTH_NAMES:
            month = _MONTH_NAMES[month_str]
            day = int(day_str)
            result = date(today.year, month, day)
            if result < today:
                result = date(today.year + 1, month, day)
            return result.isoformat()

    # "M/D" — e.g. "2/14"
    slash_date = re.match(r"(\d{1,2})/(\d{1,2})$", cleaned)
    if slash_date:
        month = int(slash_date.group(1))
        day = int(slash_date.group(2))
        result = date(today.year, month, day)
        if result < today:
            result = date(today.year + 1, month, day)
        return result.isoformat()

    raise ValueError(f"Cannot parse date: '{text}'")
