from src.models.enums import (
    Ambiance,
    BookingPlatform,
    Cuisine,
    CuisineCategory,
    NoiseLevel,
    PriceLevel,
    SeatingPreference,
)


class TestCuisine:
    def test_member_count(self):
        assert len(Cuisine) == 15

    def test_is_str_enum(self):
        assert isinstance(Cuisine.ITALIAN, str)

    def test_value_access(self):
        assert Cuisine.ITALIAN.value == "italian"
        assert Cuisine.MEXICAN.value == "mexican"
        assert Cuisine.JAPANESE.value == "japanese"
        assert Cuisine.KOREAN.value == "korean"
        assert Cuisine.CHINESE.value == "chinese"
        assert Cuisine.THAI.value == "thai"
        assert Cuisine.INDIAN.value == "indian"
        assert Cuisine.MEDITERRANEAN.value == "mediterranean"
        assert Cuisine.FRENCH.value == "french"
        assert Cuisine.AMERICAN.value == "american"
        assert Cuisine.SEAFOOD.value == "seafood"
        assert Cuisine.STEAKHOUSE.value == "steakhouse"
        assert Cuisine.PIZZA.value == "pizza"
        assert Cuisine.SUSHI.value == "sushi"
        assert Cuisine.OTHER.value == "other"

    def test_construction_from_value(self):
        assert Cuisine("italian") is Cuisine.ITALIAN
        assert Cuisine("sushi") is Cuisine.SUSHI

    def test_str_behaviour(self):
        assert Cuisine.ITALIAN == "italian"
        assert f"{Cuisine.FRENCH}" == "french"


class TestPriceLevel:
    def test_member_count(self):
        assert len(PriceLevel) == 4

    def test_is_int_enum(self):
        assert isinstance(PriceLevel.BUDGET, int)

    def test_value_access(self):
        assert PriceLevel.BUDGET.value == 1
        assert PriceLevel.MODERATE.value == 2
        assert PriceLevel.UPSCALE.value == 3
        assert PriceLevel.FINE_DINING.value == 4

    def test_construction_from_value(self):
        assert PriceLevel(1) is PriceLevel.BUDGET
        assert PriceLevel(4) is PriceLevel.FINE_DINING

    def test_int_behaviour(self):
        assert PriceLevel.BUDGET + 1 == 2
        assert PriceLevel.MODERATE < PriceLevel.UPSCALE


class TestAmbiance:
    def test_member_count(self):
        assert len(Ambiance) == 3

    def test_is_str_enum(self):
        assert isinstance(Ambiance.QUIET, str)

    def test_value_access(self):
        assert Ambiance.QUIET.value == "quiet"
        assert Ambiance.MODERATE.value == "moderate"
        assert Ambiance.LIVELY.value == "lively"

    def test_construction_from_value(self):
        assert Ambiance("quiet") is Ambiance.QUIET
        assert Ambiance("lively") is Ambiance.LIVELY


class TestNoiseLevel:
    def test_member_count(self):
        assert len(NoiseLevel) == 3

    def test_is_str_enum(self):
        assert isinstance(NoiseLevel.QUIET, str)

    def test_value_access(self):
        assert NoiseLevel.QUIET.value == "quiet"
        assert NoiseLevel.MODERATE.value == "moderate"
        assert NoiseLevel.LOUD.value == "loud"

    def test_construction_from_value(self):
        assert NoiseLevel("loud") is NoiseLevel.LOUD


class TestSeatingPreference:
    def test_member_count(self):
        assert len(SeatingPreference) == 3

    def test_is_str_enum(self):
        assert isinstance(SeatingPreference.INDOOR, str)

    def test_value_access(self):
        assert SeatingPreference.INDOOR.value == "indoor"
        assert SeatingPreference.OUTDOOR.value == "outdoor"
        assert SeatingPreference.NO_PREFERENCE.value == "no_preference"

    def test_construction_from_value(self):
        assert SeatingPreference("outdoor") is SeatingPreference.OUTDOOR


class TestBookingPlatform:
    def test_member_count(self):
        assert len(BookingPlatform) == 2

    def test_is_str_enum(self):
        assert isinstance(BookingPlatform.RESY, str)

    def test_value_access(self):
        assert BookingPlatform.RESY.value == "resy"
        assert BookingPlatform.OPENTABLE.value == "opentable"

    def test_construction_from_value(self):
        assert BookingPlatform("resy") is BookingPlatform.RESY
        assert BookingPlatform("opentable") is BookingPlatform.OPENTABLE


class TestCuisineCategory:
    def test_member_count(self):
        assert len(CuisineCategory) == 4

    def test_is_str_enum(self):
        assert isinstance(CuisineCategory.FAVORITE, str)

    def test_value_access(self):
        assert CuisineCategory.FAVORITE.value == "favorite"
        assert CuisineCategory.LIKE.value == "like"
        assert CuisineCategory.NEUTRAL.value == "neutral"
        assert CuisineCategory.AVOID.value == "avoid"

    def test_construction_from_value(self):
        assert CuisineCategory("avoid") is CuisineCategory.AVOID
