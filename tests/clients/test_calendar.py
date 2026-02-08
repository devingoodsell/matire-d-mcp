"""Tests for src.clients.calendar — Google Calendar link generation."""

from urllib.parse import unquote

from src.clients.calendar import generate_gcal_link


class TestGenerateGcalLink:
    def test_basic_url_structure(self):
        url = generate_gcal_link(
            restaurant_name="Joe's Pizza",
            restaurant_address="123 Broadway, NY",
            date="2026-02-14",
            time="19:00",
            party_size=2,
        )
        assert url.startswith("https://calendar.google.com/calendar/render?")
        assert "action=TEMPLATE" in url

    def test_title_includes_restaurant(self):
        url = generate_gcal_link(
            restaurant_name="Carbone",
            restaurant_address="181 Thompson St",
            date="2026-03-01",
            time="20:00",
            party_size=4,
        )
        assert "Dinner+at+Carbone" in url or "Dinner%20at%20Carbone" in url

    def test_date_time_formatting(self):
        url = generate_gcal_link(
            restaurant_name="Test",
            restaurant_address="123 Main St",
            date="2026-02-14",
            time="19:30",
            party_size=2,
        )
        assert "20260214T193000" in url  # start
        assert "20260214T213000" in url  # end (2 hours later)

    def test_special_characters_encoded(self):
        url = generate_gcal_link(
            restaurant_name="L'Artusi & Friends",
            restaurant_address="228 W 10th St, New York",
            date="2026-01-15",
            time="18:00",
            party_size=3,
        )
        decoded = unquote(url)
        assert "L'Artusi & Friends" in decoded

    def test_with_confirmation_id(self):
        url = generate_gcal_link(
            restaurant_name="Test",
            restaurant_address="123 Main",
            date="2026-02-14",
            time="19:00",
            party_size=2,
            confirmation_id="RSV-123",
        )
        decoded = unquote(url)
        assert "Confirmation: RSV-123" in decoded

    def test_with_platform(self):
        url = generate_gcal_link(
            restaurant_name="Test",
            restaurant_address="123 Main",
            date="2026-02-14",
            time="19:00",
            party_size=2,
            platform="Resy",
        )
        decoded = unquote(url)
        assert "Booked via Resy" in decoded

    def test_without_optional_fields(self):
        url = generate_gcal_link(
            restaurant_name="Test",
            restaurant_address="123 Main",
            date="2026-02-14",
            time="19:00",
            party_size=2,
        )
        decoded = unquote(url)
        assert "Confirmation" not in decoded
        assert "Booked via" not in decoded
        assert "Party of 2" in decoded

    def test_location_in_url(self):
        url = generate_gcal_link(
            restaurant_name="Test",
            restaurant_address="181 Thompson St, New York, NY 10012",
            date="2026-02-14",
            time="19:00",
            party_size=2,
        )
        decoded = unquote(url)
        assert "181 Thompson St" in decoded

    def test_midnight_time(self):
        url = generate_gcal_link(
            restaurant_name="Late Night Spot",
            restaurant_address="123 Main",
            date="2026-02-14",
            time="00:00",
            party_size=2,
        )
        assert "20260214T000000" in url
        assert "20260214T020000" in url
