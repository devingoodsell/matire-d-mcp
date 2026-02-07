"""Cost-free distance and walking time estimation using haversine formula."""

import math

# Earth radius in km
_EARTH_RADIUS_KM = 6371.0

# Average walking speed: ~5 km/h → ~83 m/min
_WALKING_METERS_PER_MIN = 83.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate straight-line distance between two points in km.

    Uses the haversine formula for great-circle distance.

    Args:
        lat1, lng1: First point coordinates (degrees).
        lat2, lng2: Second point coordinates (degrees).

    Returns:
        Distance in kilometres.
    """
    lat1_r, lng1_r = math.radians(lat1), math.radians(lng1)
    lat2_r, lng2_r = math.radians(lat2), math.radians(lng2)

    dlat = lat2_r - lat1_r
    dlng = lng2_r - lng1_r

    a = math.sin(dlat / 2) ** 2 + (
        math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return _EARTH_RADIUS_KM * c


def walking_minutes(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Estimate walking time between two points.

    Uses haversine distance × 1.3 Manhattan factor, then divides by
    average walking speed (~83 m/min).

    Args:
        lat1, lng1: Origin coordinates (degrees).
        lat2, lng2: Destination coordinates (degrees).

    Returns:
        Estimated walking time in minutes (rounded up).
    """
    straight_km = haversine_km(lat1, lng1, lat2, lng2)
    # Manhattan grid factor: actual walking distance ≈ 1.3× straight-line
    walking_m = straight_km * 1.3 * 1000
    return math.ceil(walking_m / _WALKING_METERS_PER_MIN)
