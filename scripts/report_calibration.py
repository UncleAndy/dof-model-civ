"""Report the calibrated DoF model on a real captured game state.

Prints, per entity, the DoF in options next to the components it was built from,
so every constant in `env/config.py` can be checked against real data instead of
trusted. Also prints the bridge calibration (what the action bridge will project
for production, research and founding) and the system index.

Usage:  .venv/bin/python scripts/report_calibration.py [fixture.json] [record]
"""
import json
import sys

from env.config import (  # noqa: E402
    CORE_DOF_SCALE, DOF_SCALE, CITY_CEIL, TECH_NOMINAL_TURNS, W_FUTURE_UNIT,
)
from env.entity_extractor import (  # noqa: E402
    GameStateExtractor, compute_total_dof_index, city_options, unit_options,
    health_ratio, is_population_carrier, tech_options,
)


def print_catalogue(bridge, obs) -> None:
    """Unit types priced by the same formula, from the ruleset's own specs."""
    spec_by_name: dict[str, dict] = {}
    for t in (obs.get('tech') or {}).values():
        for spec in (t.get('sup_units') or []):
            name = str(spec.get('rule_name') or spec.get('name') or '').strip()
            spec_by_name.setdefault(name, spec)

    print("\n=== unit catalogue (option counts from real type parameters)")
    rows = sorted(bridge.unit_type_options.items(), key=lambda kv: -kv[1])
    for name, opts in rows[:10]:
        print(f"    {name:<22} {opts:6.3f} options")
    print("    ... required relations: a soldier's CURRENT DoF must exceed a "
          "settler's,\n        while the settler's TOTAL DoF must exceed a "
          "soldier's (its future is the city):")
    for wanted in ('Warriors', 'Musketeers', 'Phalanx', 'Legion', 'Knights'):
        spec = spec_by_name.get(wanted)
        if spec is None:
            continue
        opts, cur, fut = unit_options(spec)
        print(f"    {wanted:<12} total={opts:6.3f}  current={DOF_SCALE * cur:5.3f}"
              f"  future={DOF_SCALE * W_FUTURE_UNIT * fut:5.3f}")


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else 'tests/fixtures/real_obs_01.json'
    recs = json.load(open(path))
    rec = recs[0]
    obs, info, turn = rec['observation'], rec['info'], rec.get('turn', 1)

    extractor = GameStateExtractor(my_player_id=0)
    result = extractor.extract(obs, info, turn)
    state = result.state

    print(f"=== turn {turn}: {len(state.entities)} entities, "
          f"index = {compute_total_dof_index(state):.4f}, "
          f"sink = {state.dof_sink:.4f}")
    print(f"    DOF_SCALE={DOF_SCALE}, CITY_CEIL={CITY_CEIL}, "
          f"CORE_DOF_SCALE={CORE_DOF_SCALE}")

    print("\n=== units (real fields)")
    for uid, u in (obs.get('unit') or {}).items():
        opts, cur, fut = unit_options(u)
        entity = state.entities.get(f'unit_{uid}')
        print(f"  unit_{uid:<5} {str(u.get('type_rule_name')):<10} "
              f"hp={u.get('health')}/{u.get('type_hp')} "
              f"atk={u.get('type_attack_strength')} def={u.get('type_defense_strength')} "
              f"fp={u.get('type_firepower')} mv={u.get('type_move_rate')} "
              f"vis={u.get('type_vision_radius_sq')} worker={u.get('type_worker')} "
              f"carrier={is_population_carrier(u)}")
        print(f"        hr={health_ratio(u):.3f}  s_current={cur:.4f}  s_future={fut:.4f}"
              f"  → options={opts:.3f}  (field current_dof={entity.current_dof:.4f})")

    print("\n=== cities (three-multiplier scheme)")
    for cid, c in (obs.get('city') or {}).items():
        entity = state.entities.get(f'city_{cid}')
        print(f"  city_{cid:<5} {c.get('name')} size={c.get('size')} "
              f"surplus_food={c.get('surplus_food')} stock={c.get('food_stock')}/"
              f"{c.get('granary_size')} improv={sum(1 for x in (c.get('improvements') or []) if x)} "
              f"shield={c.get('surplus_shield')} trade={c.get('surplus_trade')} "
              f"gold={c.get('surplus_gold')} sci={c.get('science')} lux={c.get('luxury')} "
              f"corr/waste/poll={c.get('city_corruption')}/{c.get('city_waste')}/"
              f"{c.get('city_pollution')} ppl=+{c.get('ppl_happy')}/-{c.get('ppl_unhappy')}")
        print(f"        → options={entity.dof_count:.3f} "
              f"(field current_dof={entity.current_dof:.4f})")

    print("\n=== technologies")
    techs = obs.get('tech') or {}
    known = [t for t in techs.values() if t.get('inv_state')]
    print(f"  {len(techs)} technologies, known={len(known)}")
    for t in known[:5]:
        print(f"    known: {str(t.get('name')):<22} options="
              f"{tech_options(t):.3f} (units={len(t.get('sup_units') or [])}, "
              f"improvements={len(t.get('sup_improvements') or [])})")

    bridge = state.bridge
    print("\n=== bridge calibration (state-derived action pricing)")
    print(f"  new_city_options = {bridge.new_city_options:.3f} "
          f"(a founded settlement, this empire's conditions, no improvements)")
    print(f"  improvement_gain = {bridge.improvement_gain}")
    print(f"  unit catalogue = {len(bridge.unit_type_options)} types, "
          f"improvement catalogue = {len(bridge.improvement_options)} types")
    top = sorted(bridge.tech_research_gain.items(), key=lambda kv: -kv[1])[:5]
    print(f"  research rate (options/turn, nominal horizon {TECH_NOMINAL_TURNS} "
          f"turns for technologies that are not the current research):")
    for k, v in top:
        print(f"    {k:<10} +{v:.4f}")

    print_catalogue(bridge, obs)

    settler = state.entities.get('unit_113')
    if settler is not None:
        print(f"\n  founding delta (unit_113 Settlers → size-1 city): "
              f"{bridge.new_city_options - settler.dof_count:+.3f} options")


if __name__ == '__main__':
    main()
