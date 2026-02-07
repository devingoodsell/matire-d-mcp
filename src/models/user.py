from pydantic import BaseModel, ConfigDict

from src.models.enums import Ambiance, CuisineCategory, PriceLevel, SeatingPreference


class UserPreferences(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    rating_threshold: float = 4.0
    noise_preference: Ambiance = Ambiance.MODERATE
    seating_preference: SeatingPreference = SeatingPreference.NO_PREFERENCE
    max_walk_minutes: int = 15
    default_party_size: int = 2


class DietaryRestriction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    restriction: str


class CuisinePreference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cuisine: str
    category: CuisineCategory


class PricePreference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price_level: PriceLevel
    acceptable: bool = True


class Location(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    address: str
    lat: float
    lng: float
    walk_radius_minutes: int = 15


class Person(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    dietary_restrictions: list[str] = []
    no_alcohol: bool = False
    notes: str | None = None


class Group(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    member_ids: list[int] = []
    member_names: list[str] = []
