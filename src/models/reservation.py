from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.models.enums import BookingPlatform


class Reservation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    restaurant_id: str
    restaurant_name: str
    platform: BookingPlatform
    platform_confirmation_id: str | None = None
    date: str
    time: str
    party_size: int
    special_requests: str | None = None
    status: str = "confirmed"
    created_at: datetime | None = None
    cancelled_at: datetime | None = None


class BookingResult(BaseModel):
    success: bool
    reservation: Reservation | None = None
    error: str | None = None
    deep_link: str | None = None
    message: str
