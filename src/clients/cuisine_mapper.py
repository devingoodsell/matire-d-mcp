"""Map Google Places types to our Cuisine enum."""

from src.models.enums import Cuisine

# Google Places API (New) primaryType values → our Cuisine enum
GOOGLE_TYPE_TO_CUISINE: dict[str, Cuisine] = {
    "italian_restaurant": Cuisine.ITALIAN,
    "mexican_restaurant": Cuisine.MEXICAN,
    "japanese_restaurant": Cuisine.JAPANESE,
    "korean_restaurant": Cuisine.KOREAN,
    "chinese_restaurant": Cuisine.CHINESE,
    "thai_restaurant": Cuisine.THAI,
    "indian_restaurant": Cuisine.INDIAN,
    "mediterranean_restaurant": Cuisine.MEDITERRANEAN,
    "french_restaurant": Cuisine.FRENCH,
    "american_restaurant": Cuisine.AMERICAN,
    "seafood_restaurant": Cuisine.SEAFOOD,
    "steak_house": Cuisine.STEAKHOUSE,
    "pizza_restaurant": Cuisine.PIZZA,
    "sushi_restaurant": Cuisine.SUSHI,
}

# Additional types array entries that hint at cuisine
GOOGLE_TYPES_HINTS: dict[str, Cuisine] = {
    "barbecue_restaurant": Cuisine.AMERICAN,
    "hamburger_restaurant": Cuisine.AMERICAN,
    "ramen_restaurant": Cuisine.JAPANESE,
    "brunch_restaurant": Cuisine.AMERICAN,
    "breakfast_restaurant": Cuisine.AMERICAN,
    "vegan_restaurant": Cuisine.OTHER,
    "vegetarian_restaurant": Cuisine.OTHER,
    "vietnamese_restaurant": Cuisine.OTHER,
    "greek_restaurant": Cuisine.MEDITERRANEAN,
    "turkish_restaurant": Cuisine.MEDITERRANEAN,
    "lebanese_restaurant": Cuisine.MEDITERRANEAN,
    "spanish_restaurant": Cuisine.MEDITERRANEAN,
    "middle_eastern_restaurant": Cuisine.MEDITERRANEAN,
    "indonesian_restaurant": Cuisine.OTHER,
    "caribbean_restaurant": Cuisine.OTHER,
    "african_restaurant": Cuisine.OTHER,
    "brazilian_restaurant": Cuisine.OTHER,
    "peruvian_restaurant": Cuisine.OTHER,
}


def map_cuisine(primary_type: str | None, types: list[str] | None = None) -> list[str]:
    """Map Google Places types to cuisine strings.

    Args:
        primary_type: The primaryType field from Google Places response.
        types: The types array from Google Places response.

    Returns:
        List of cuisine strings (values from our Cuisine enum).
        Falls back to ["other"] if no match found.
    """
    cuisines: list[str] = []

    # Check primary type first (most specific)
    if primary_type:
        matched = GOOGLE_TYPE_TO_CUISINE.get(primary_type)
        if matched:
            cuisines.append(matched.value)
        else:
            hint = GOOGLE_TYPES_HINTS.get(primary_type)
            if hint:
                cuisines.append(hint.value)

    # Check types array for additional matches
    if types:
        for t in types:
            matched = GOOGLE_TYPE_TO_CUISINE.get(t)
            if matched and matched.value not in cuisines:
                cuisines.append(matched.value)
            elif not matched:
                hint = GOOGLE_TYPES_HINTS.get(t)
                if hint and hint.value not in cuisines:
                    cuisines.append(hint.value)

    return cuisines if cuisines else [Cuisine.OTHER.value]
