from src.clients.cuisine_mapper import map_cuisine


class TestMapCuisinePrimaryTypeMainMap:
    """primaryType found in GOOGLE_TYPE_TO_CUISINE."""

    def test_italian_restaurant_returns_italian(self):
        result = map_cuisine("italian_restaurant")
        assert result == ["italian"]

    def test_japanese_restaurant_returns_japanese(self):
        result = map_cuisine("japanese_restaurant")
        assert result == ["japanese"]

    def test_steak_house_returns_steakhouse(self):
        result = map_cuisine("steak_house")
        assert result == ["steakhouse"]


class TestMapCuisinePrimaryTypeHints:
    """primaryType not in main map but found in GOOGLE_TYPES_HINTS."""

    def test_ramen_restaurant_returns_japanese(self):
        result = map_cuisine("ramen_restaurant")
        assert result == ["japanese"]

    def test_barbecue_restaurant_returns_american(self):
        result = map_cuisine("barbecue_restaurant")
        assert result == ["american"]

    def test_greek_restaurant_returns_mediterranean(self):
        result = map_cuisine("greek_restaurant")
        assert result == ["mediterranean"]

    def test_vegan_restaurant_returns_other(self):
        result = map_cuisine("vegan_restaurant")
        assert result == ["other"]


class TestMapCuisineTypesArrayOnly:
    """primaryType is None; cuisines come from the types array."""

    def test_unknown_primary_falls_back_to_types(self):
        result = map_cuisine("unknown_place", ["italian_restaurant"])
        assert result == ["italian"]

    def test_types_array_main_map_match(self):
        result = map_cuisine(None, ["korean_restaurant", "chinese_restaurant"])
        assert result == ["korean", "chinese"]

    def test_types_array_hint_match(self):
        result = map_cuisine(None, ["hamburger_restaurant"])
        assert result == ["american"]

    def test_types_array_with_hints_but_no_main_map(self):
        result = map_cuisine(None, ["turkish_restaurant", "lebanese_restaurant"])
        assert result == ["mediterranean"]

    def test_types_array_mixed_main_and_hints(self):
        result = map_cuisine(None, ["thai_restaurant", "ramen_restaurant"])
        assert result == ["thai", "japanese"]


class TestMapCuisineCombined:
    """Both primaryType and types contribute cuisines."""

    def test_primary_and_types_combined(self):
        result = map_cuisine("italian_restaurant", ["japanese_restaurant"])
        assert result == ["italian", "japanese"]

    def test_no_duplicates_when_primary_and_types_match_same(self):
        result = map_cuisine("italian_restaurant", ["italian_restaurant"])
        assert result == ["italian"]

    def test_no_duplicates_primary_hint_and_types_same_cuisine(self):
        """primaryType matches via hints to 'american', types also has american hint."""
        result = map_cuisine(
            "barbecue_restaurant",
            ["hamburger_restaurant", "brunch_restaurant"],
        )
        assert result == ["american"]

    def test_no_duplicates_primary_main_and_types_hint_same_cuisine(self):
        """primaryType maps to 'japanese' via main map, types has ramen (also japanese)."""
        result = map_cuisine("japanese_restaurant", ["ramen_restaurant"])
        assert result == ["japanese"]

    def test_primary_and_types_with_unknown_entries(self):
        """Unknown types in the array are silently skipped."""
        result = map_cuisine("french_restaurant", ["cafe", "restaurant", "food"])
        assert result == ["french"]


class TestMapCuisineNoMatch:
    """No match in either primary or types results in ["other"]."""

    def test_unknown_primary_no_types_returns_other(self):
        result = map_cuisine("some_unknown_type")
        assert result == ["other"]

    def test_none_primary_none_types_returns_other(self):
        result = map_cuisine(None, None)
        assert result == ["other"]

    def test_none_primary_no_types_arg_returns_other(self):
        result = map_cuisine(None)
        assert result == ["other"]

    def test_unknown_primary_empty_types_returns_other(self):
        result = map_cuisine("totally_unknown", [])
        assert result == ["other"]

    def test_none_primary_empty_types_returns_other(self):
        result = map_cuisine(None, [])
        assert result == ["other"]

    def test_unknown_primary_unknown_types_returns_other(self):
        result = map_cuisine("foo", ["bar", "baz"])
        assert result == ["other"]


class TestMapCuisineTypesHintDedup:
    """Ensure hint matches in types do not produce duplicates."""

    def test_types_multiple_hints_same_cuisine_deduped(self):
        """Multiple hints mapping to 'mediterranean' produce a single entry."""
        result = map_cuisine(
            None,
            ["greek_restaurant", "turkish_restaurant", "spanish_restaurant"],
        )
        assert result == ["mediterranean"]

    def test_types_main_match_skips_duplicate_hint(self):
        """A main-map match followed by a hint to the same cuisine is not duplicated."""
        result = map_cuisine(None, ["japanese_restaurant", "ramen_restaurant"])
        assert result == ["japanese"]

    def test_primary_main_map_types_hint_same_cuisine(self):
        """Primary matches main map to 'american', types hint also 'american'."""
        result = map_cuisine("american_restaurant", ["barbecue_restaurant"])
        assert result == ["american"]
