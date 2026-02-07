from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.models.enums import BookingPlatform


class Restaurant(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    address: str
    lat: float
    lng: float
    cuisine: list[str] = []
    price_level: int | None = None
    rating: float | None = None
    review_count: int | None = None
    phone: str | None = None
    website: str | None = None
    hours: dict | None = None
    resy_venue_id: str | None = None
    opentable_id: str | None = None
    cached_at: datetime | None = None


class TimeSlot(BaseModel):
    time: str
    type: str | None = None
    platform: BookingPlatform
    config_id: str | None = None


class AvailabilityResult(BaseModel):
    restaurant_id: str
    restaurant_name: str
    date: str
    slots: list[TimeSlot]
    platform: BookingPlatform
    checked_at: datetime
