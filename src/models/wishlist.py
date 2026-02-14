from pydantic import BaseModel, ConfigDict


class WishlistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    restaurant_id: str
    restaurant_name: str
    notes: str | None = None
    tags: list[str] = []
    added_date: str | None = None
