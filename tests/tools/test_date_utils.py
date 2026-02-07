"""Tests for natural-language date parsing."""

from datetime import date, timedelta

import pytest

from src.tools.date_utils import parse_date

# Fixed reference date: Wednesday, 2026-02-11
FIXED_TODAY = date(2026, 2, 11)


class TestISOPassthrough:
    def test_iso_date_returned_as_is(self):
        assert parse_date("2026-02-14", today=FIXED_TODAY) == "2026-02-14"

    def test_iso_date_with_whitespace(self):
        assert parse_date("  2026-02-14  ", today=FIXED_TODAY) == "2026-02-14"


class TestRelativeDays:
    def test_today(self):
        assert parse_date("today", today=FIXED_TODAY) == "2026-02-11"

    def test_tomorrow(self):
        assert parse_date("tomorrow", today=FIXED_TODAY) == "2026-02-12"


class TestDayName:
    def test_bare_saturday(self):
        # FIXED_TODAY is Wednesday (weekday=2), Saturday is weekday=5
        # days_ahead = (5 - 2) % 7 = 3 -> 2026-02-14
        assert parse_date("saturday", today=FIXED_TODAY) == "2026-02-14"

    def test_this_saturday(self):
        # "this saturday" behaves the same as bare "saturday"
        assert parse_date("this saturday", today=FIXED_TODAY) == "2026-02-14"

    def test_bare_day_name_same_weekday_skips_to_next_week(self):
        # FIXED_TODAY is Wednesday, so "wednesday" should give next Wednesday
        # days_ahead = (2 - 2) % 7 = 0, then set to 7
        assert parse_date("wednesday", today=FIXED_TODAY) == "2026-02-18"

    def test_this_day_same_weekday_skips_to_next_week(self):
        assert parse_date("this wednesday", today=FIXED_TODAY) == "2026-02-18"


class TestNextDayName:
    def test_next_saturday(self):
        # "next saturday": days_ahead = (5 - 2) % 7 = 3, non-zero so no +7 fix,
        # then +7 for "next" = 10 -> 2026-02-21
        assert parse_date("next saturday", today=FIXED_TODAY) == "2026-02-21"

    def test_next_same_weekday(self):
        # "next wednesday": days_ahead = (2 - 2) % 7 = 0, set to 7,
        # then +7 for "next" = 14 -> 2026-02-25
        assert parse_date("next wednesday", today=FIXED_TODAY) == "2026-02-25"

    def test_next_monday(self):
        # "next monday": days_ahead = (0 - 2) % 7 = 5, non-zero,
        # then +7 for "next" = 12 -> 2026-02-23
        assert parse_date("next monday", today=FIXED_TODAY) == "2026-02-23"

    def test_next_unknown_day_falls_through(self):
        # "next gibberish" — day_name not in _DAY_NAMES, falls through to later parsers
        with pytest.raises(ValueError, match="Cannot parse date"):
            parse_date("next gibberish", today=FIXED_TODAY)


class TestMonthDay:
    def test_feb_14_abbreviated(self):
        assert parse_date("Feb 14", today=FIXED_TODAY) == "2026-02-14"

    def test_february_14_full(self):
        assert parse_date("February 14", today=FIXED_TODAY) == "2026-02-14"

    def test_month_day_in_the_past_rolls_to_next_year(self):
        # Jan 5 is before FIXED_TODAY (Feb 11), so it should roll to 2027
        assert parse_date("Jan 5", today=FIXED_TODAY) == "2027-01-05"

    def test_month_day_today_stays_current_year(self):
        # Feb 11 is exactly today; date(2026, 2, 11) < FIXED_TODAY is False (equal),
        # so it stays 2026
        assert parse_date("Feb 11", today=FIXED_TODAY) == "2026-02-11"

    def test_unknown_month_name_raises(self):
        with pytest.raises(ValueError, match="Cannot parse date"):
            parse_date("Smarch 14", today=FIXED_TODAY)


class TestSlashDate:
    def test_slash_date_future(self):
        assert parse_date("2/14", today=FIXED_TODAY) == "2026-02-14"

    def test_slash_date_past_rolls_to_next_year(self):
        assert parse_date("1/5", today=FIXED_TODAY) == "2027-01-05"

    def test_slash_date_today_stays_current_year(self):
        assert parse_date("2/11", today=FIXED_TODAY) == "2026-02-11"


class TestUnparseable:
    def test_gibberish_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot parse date"):
            parse_date("gibberish", today=FIXED_TODAY)

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot parse date"):
            parse_date("", today=FIXED_TODAY)


class TestDefaultToday:
    def test_today_uses_real_date_when_no_override(self):
        result = parse_date("today")
        assert result == date.today().isoformat()

    def test_tomorrow_uses_real_date_when_no_override(self):
        result = parse_date("tomorrow")
        expected = (date.today() + timedelta(days=1)).isoformat()
        assert result == expected
