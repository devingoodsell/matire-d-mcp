import math

from src.clients.distance import haversine_km, walking_minutes

# Coordinates for reference points
_NYC_LAT, _NYC_LNG = 40.7128, -74.0060
_BOSTON_LAT, _BOSTON_LNG = 42.3601, -71.0589

# Two nearby points in Manhattan (~1 km apart)
_TIMES_SQ_LAT, _TIMES_SQ_LNG = 40.7580, -73.9855
_BRYANT_PARK_LAT, _BRYANT_PARK_LNG = 40.7536, -73.9832


class TestHaversineKmSamePoint:
    """Same point should return zero distance."""

    def test_same_point_returns_zero(self):
        assert haversine_km(_NYC_LAT, _NYC_LNG, _NYC_LAT, _NYC_LNG) == 0.0

    def test_same_point_at_origin(self):
        assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0


class TestHaversineKmKnownDistance:
    """Verify against known city-pair distances."""

    def test_nyc_to_boston(self):
        dist = haversine_km(_NYC_LAT, _NYC_LNG, _BOSTON_LAT, _BOSTON_LNG)
        # Great-circle distance NYC-Boston is approximately 306 km
        assert 300 < dist < 315

    def test_symmetry(self):
        """Distance A->B should equal distance B->A."""
        d1 = haversine_km(_NYC_LAT, _NYC_LNG, _BOSTON_LAT, _BOSTON_LNG)
        d2 = haversine_km(_BOSTON_LAT, _BOSTON_LNG, _NYC_LAT, _NYC_LNG)
        assert d1 == d2


class TestHaversineKmNearbyPoints:
    """Short distances within Manhattan."""

    def test_times_sq_to_bryant_park(self):
        dist = haversine_km(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        # Roughly 0.5 km apart
        assert 0.3 < dist < 0.8

    def test_nearby_distance_positive(self):
        dist = haversine_km(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        assert dist > 0


class TestWalkingMinutesSamePoint:
    """Walking time for the same point should be zero."""

    def test_same_point_returns_zero(self):
        result = walking_minutes(_NYC_LAT, _NYC_LNG, _NYC_LAT, _NYC_LNG)
        assert result == 0

    def test_same_point_type_is_int(self):
        result = walking_minutes(_NYC_LAT, _NYC_LNG, _NYC_LAT, _NYC_LNG)
        assert isinstance(result, int)


class TestWalkingMinutesKnownDistance:
    """Verify walking time calculation against manual computation."""

    def test_one_km_straight_line(self):
        """For a 1 km straight-line distance: ceil(1.3 * 1000 / 83) = ceil(15.66) = 16."""
        # Pick two points roughly 1 km apart
        # We'll compute this from the actual haversine result
        dist_km = haversine_km(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        expected = math.ceil(dist_km * 1.3 * 1000 / 83.0)
        result = walking_minutes(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        assert result == expected

    def test_nyc_to_boston_walking(self):
        """Long distance: verify the formula is applied correctly."""
        dist_km = haversine_km(_NYC_LAT, _NYC_LNG, _BOSTON_LAT, _BOSTON_LNG)
        expected = math.ceil(dist_km * 1.3 * 1000 / 83.0)
        result = walking_minutes(_NYC_LAT, _NYC_LNG, _BOSTON_LAT, _BOSTON_LNG)
        assert result == expected


class TestWalkingMinutesCeilBehavior:
    """Walking minutes always rounds up (math.ceil)."""

    def test_result_always_rounds_up(self):
        """The result should be >= the raw floating-point calculation."""
        dist_km = haversine_km(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        raw = dist_km * 1.3 * 1000 / 83.0
        result = walking_minutes(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        assert result >= raw
        # Should be the smallest integer >= raw
        assert result == math.ceil(raw)

    def test_result_is_integer(self):
        result = walking_minutes(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        assert isinstance(result, int)

    def test_walking_always_positive_for_different_points(self):
        result = walking_minutes(
            _TIMES_SQ_LAT, _TIMES_SQ_LNG,
            _BRYANT_PARK_LAT, _BRYANT_PARK_LNG,
        )
        assert result > 0
