"""
Measured action → DoF deltas (empirical calibration for the bridge).

Why this file exists
--------------------
The bridge used to project DoF changes from intuition: `fortify +0.02`,
`goto +0.01`, `build_city +0.30`, `set_tax +0.01`, `research +0.05`. Measured on
live games (`scripts/measure_action_delta.py`, 2026-09-25, turn-1 states with 95
entities, index = 3.2037), those numbers turned out to be fiction — and one of
them had the wrong sign:

    unit/103/keep_activity        Δindex = +0.0000   (projected  0.00)
    unit/113/build_city           Δindex = -0.3228   (projected +0.30)  <-- inverted
        unit_113: 0.1450 -> absent
        city_121: absent -> 0.1050
    unit/114/goto_0               Δindex = +0.0000   (projected +0.01)
    unit/116/fortify              Δindex = +0.0000   (projected +0.02)
    gov/0/change_gov_*            Δindex = +0.0000   (projected +0.02/city)
    gov/0/set_sci_lux_tax_*       Δindex = +0.0000   (projected +0.01/city)
    tech/cur_player/research_*    Δindex = +0.0000   (projected +0.05)
    tech/cur_player/set_tech_goal Δindex = +0.0000   (projected  0.00)

Consequence of the guesses: DOF-Core "gained" DoF on paper for actions that
change nothing, and for `build_city` it actively traded a flexible Settler for a
less flexible size-1 city while believing it improved the system. In a 7-agent ×
10-episode × 30-turn tournament this is why doing nothing scored best (3.20) and
every acting agent scored lower (1.57-1.74; random, which founds the most cities,
collapsed to 0.09).

So: the table below is the calibration source of truth. Actions with no measured
effect are 0.0, not a plausible-looking positive number. Re-measure with
`python scripts/measure_action_delta.py` after changing the extractor's DoF model,
and update this table — but never replace a measurement with an estimate.

Attribution: the measured value is a *system* delta caused by the action; it is
attributed to the acting entity so DOF-Core can weigh it (and veto it when it
collapses a reversible, non-aggressor entity).
"""
from __future__ import annotations

# Measurement metadata — keep this honest when refreshing the table.
MEASURED_ON = "2026-09-25"
MEASURED_TURNS = 1
MEASURED_ENTITIES = 95
MEASURED_ROOT_INDEX = 3.2037

# Keys are (ctrl_type, action-name prefix). Longest prefix wins.
MEASURED_ACTION_DELTAS: dict[tuple[str, str], float] = {
    # ── unit controller ──────────────────────────────────────────────────────
    ("unit", "keep_activity"): 0.0,
    ("unit", "goto"): 0.0,
    ("unit", "fortify"): 0.0,
    ("unit", "fortress"): 0.0,
    ("unit", "sentry"): 0.0,
    ("unit", "irrigation"): 0.0,
    ("unit", "mine"): 0.0,
    ("unit", "plant"): 0.0,
    ("unit", "cultivate"): 0.0,
    ("unit", "transform_terrain"): 0.0,
    ("unit", "road"): 0.0,
    ("unit", "railroad"): 0.0,
    # Founding is NOT listed here on purpose: with the population model in place it
    # is no longer a constant. It swaps the settler's own DoF for a size-1 city's
    # DoF, so the bridge derives it from the current state
    # (`env.action_mapper._founding_delta`). Before the population fix this was
    # measured at -0.3228 (city 0.105 < settler 0.145); after the fix a size-1 city
    # (0.537) comfortably exceeds a fresh settler (0.45), so founding is a gain.
    # ── government / economy controller ──────────────────────────────────────
    ("gov", "change_gov"): 0.0,
    ("gov", "set_sci_lux_tax"): 0.0,
    ("gov", "set_tax"): 0.0,
    ("gov", "set_luxury"): 0.0,
    # ── technology controller ────────────────────────────────────────────────
    ("tech", "research_tech"): 0.0,
    ("tech", "set_tech_goal"): 0.0,
    # ── diplomacy controller ────────────────────────────────────────────────
    ("dipl", "add_clause"): 0.0,
    ("dipl", "cancel_treaty"): 0.0,
    ("dipl", "accept_treaty"): 0.0,
    ("dipl", "stop_negotiation"): 0.0,
    # ── player controller ───────────────────────────────────────────────────
    ("player", "chat"): 0.0,
}

# The old guess-based projections, kept only so the contrast is auditable in
# tests and in the README. Do not use these for decisions.
SUPERSEDED_GUESSES: dict[str, float] = {
    "fortify": 0.02,
    "goto": 0.01,
    "build_road": 0.05,
    "build_city": 0.30,
    "found_city": 0.30,
    "set_tax": 0.01,
    "set_sci_lux_tax": 0.01,
    "change_gov": 0.02,
    "research_tech": 0.05,
}


def measured_delta(ctrl_type: str, action_name: str) -> float | None:
    """Look up the measured DoF delta for an action, or None if unmeasured.

    Matching is by action-name prefix so parameterised names resolve to their
    base action (`set_sci_lux_tax_0_40_60` → `set_sci_lux_tax`). The longest
    matching prefix wins.
    """
    name = action_name or ""
    best: tuple[int, float] | None = None
    for (ctrl, prefix), delta in MEASURED_ACTION_DELTAS.items():
        if ctrl != ctrl_type:
            continue
        if name.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), delta)
    return None if best is None else best[1]


def measured_delta_any_controller(action_name: str) -> float | None:
    """Same lookup, ignoring the controller (useful for roll-ups)."""
    for ctrl in {c for c, _ in MEASURED_ACTION_DELTAS}:
        delta = measured_delta(ctrl, action_name)
        if delta is not None:
            return delta
    return None