from pydantic import BaseModel, ConfigDict

from src.models.enums import NoiseLevel


class Visit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    restaurant_id: str
    restaurant_name: str
    date: str
    party_size: int
    companions: list[str] = []
    source: str = "booked"


class VisitReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    visit_id: int
    would_return: bool
    overall_rating: int | None = None
    ambiance_rating: int | None = None
    noise_level: NoiseLevel | None = None
    notes: str | None = None


class DishReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    visit_id: int
    dish_name: str
    rating: int
    would_order_again: bool
    notes: str | None = None
