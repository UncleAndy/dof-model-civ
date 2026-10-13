"""Trace aid for identifying production types that the city can set now."""

from brain.forecast import live


def test_production_offer_names_are_sorted_and_exclude_unavailable_actions():
    formatter = getattr(live, "_production_offer_names", None)
    assert formatter is not None, "production trace must expose the server's offered types"
    assert formatter({
        "produce_Warriors": {"enabled": True},
        "produce_Workers": {"enabled": True},
        "produce_Barracks": {"enabled": True},
        "produce_Settlers": {},
        "city_buy_production": {"enabled": True},
    }) == ("Barracks", "Warriors", "Workers")
