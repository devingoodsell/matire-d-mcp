from enum import IntEnum, StrEnum


class Cuisine(StrEnum):
    ITALIAN = "italian"
    MEXICAN = "mexican"
    JAPANESE = "japanese"
    KOREAN = "korean"
    CHINESE = "chinese"
    THAI = "thai"
    INDIAN = "indian"
    MEDITERRANEAN = "mediterranean"
    FRENCH = "french"
    AMERICAN = "american"
    SEAFOOD = "seafood"
    STEAKHOUSE = "steakhouse"
    PIZZA = "pizza"
    SUSHI = "sushi"
    OTHER = "other"


class PriceLevel(IntEnum):
    BUDGET = 1
    MODERATE = 2
    UPSCALE = 3
    FINE_DINING = 4


class Ambiance(StrEnum):
    QUIET = "quiet"
    MODERATE = "moderate"
    LIVELY = "lively"


class NoiseLevel(StrEnum):
    QUIET = "quiet"
    MODERATE = "moderate"
    LOUD = "loud"


class SeatingPreference(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    NO_PREFERENCE = "no_preference"


class BookingPlatform(StrEnum):
    RESY = "resy"
    OPENTABLE = "opentable"


class CuisineCategory(StrEnum):
    FAVORITE = "favorite"
    LIKE = "like"
    NEUTRAL = "neutral"
    AVOID = "avoid"
