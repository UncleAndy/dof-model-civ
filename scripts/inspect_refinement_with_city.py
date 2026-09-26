"""Second run of the refinement loop — on a state that actually HAS a city.

Three things happen here, in order:

1. **Map indexing proved, not guessed.** The observation carries `map['unit']`
   and `map['unit_owner']` arrays alongside each unit's own (x, y), so the index
   order is decidable: whichever convention flags a unit exactly where the unit
   says it is. That is the prerequisite for judging a founding site from tile
   yields.
2. **A city is founded through the game's own API** (not by the model), so the
   following turn shows a real city to reconcile the model's city rules against.
3. **The first prediction/observation pair is recorded**: what the model believed
   a new city would be worth before founding, against what the city actually is.
   That pair is exactly the raw material of the statistical refinement path.

Usage: .venv/bin/python scripts/inspect_refinement_with_city.py [--max-turns 12]
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings('ignore')
os.environ['PYTHONWARNINGS'] = 'ignore'

_p = argparse.ArgumentParser()
_p.add_argument('--max-turns', type=int, default=12)
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports
from civrealm.agents import RandomAgent

from env.entity_extractor import (
    GameStateExtractor, as_dict, as_list, city_options, unit_options,
)


def prove_indexing(obs: dict) -> str:
    """Decide the map array order from the units' own coordinates."""
    import numpy as np

    mp = as_dict(obs.get('map'))
    units = as_dict(obs.get('unit'))
    unit_layer = mp.get('unit')
    if unit_layer is None or not units:
        return 'unknown (no map unit layer)'
    unit_layer = np.asarray(unit_layer)
    yx = xy = 0
    for u in units.values():
        if not isinstance(u, dict):
            continue
        x, y = int(u.get('x', -1)), int(u.get('y', -1))
        if x < 0 or y < 0:
            continue
        try:
            if bool(np.any(unit_layer[y][x])):
                yx += 1
            if bool(np.any(unit_layer[x][y])):
                xy += 1
        except IndexError:
            continue
    verdict = ('[y][x]' if yx > xy else '[x][y]' if xy > yx else 'undecided')
    return f'matches: [y][x]={yx} [x][y]={xy} -> {verdict}'


def tile_yields(obs: dict, x: int, y: int, order: str) -> list[int] | None:
    mp = as_dict(obs.get('map'))
    out = mp.get('output')
    if out is None:
        return None
    try:
        row = out[y][x] if order == '[y][x]' else out[x][y]
        return [int(v) for v in row]
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    fc_args['port'] = Ports.get()
    env = gymnasium.make('civrealm/FreecivBase-v0', client_port=fc_args['port'])
    obs, info = env.reset()
    extractor = GameStateExtractor(my_player_id=0)
    try:
        extractor.my_player_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        pass

    order_line = prove_indexing(obs)
    print(f'=== map indexing: {order_line}')

    settler = next((u for u in as_dict(obs.get('unit')).values()
                    if 'settler' in str(u.get('type_rule_name', '')).lower()), None)
    if settler is not None:
        x, y = int(settler.get('x', -1)), int(settler.get('y', -1))
        order = order_line.rsplit('->', 1)[-1].strip()
        print(f'    settler tile ({x},{y}) yields={tile_yields(obs, x, y, order)}')

    # What does the model believe a new city is worth right now?
    before = extractor.extract(obs, info, info.get('turn', 0))
    predicted_new_city = before.state.bridge.new_city_options
    settlers = {eid: e for eid, e in before.state.entities.items()
                if eid.startswith('unit_') and 'settler' in eid}
    print(f'=== before founding: model entries={len(extractor.model.entries)}, '
          f'predicted new city = {predicted_new_city:.3f} options, '
          f'own cities = {[k for k in before.state.entities if k.startswith("city_")]}')

    # Found a city through the game's own agent, then end the turn.
    agent = RandomAgent()
    found_round = None
    for turn in range(_ARGS.max_turns):
        action = agent.act(obs, info)
        name = action[2] if isinstance(action, tuple) and len(action) > 2 else None
        if action is None or (name and 'build' in str(name)):
            obs, _r, term, trunc, info = env.step(action)
            if name and 'build' in str(name):
                found_round = turn
                print(f'    turn {info.get("turn")}: issued {name}')
                # end this turn so the city exists in the next observation
                obs, _r, term, trunc, info = env.step(None)
                break
        else:
            obs, _r, term, trunc, info = env.step(action)
        if term or trunc:
            break

    after = extractor.extract(obs, info, info.get('turn', 0))
    model = extractor.model
    cities = [e for eid, e in after.state.entities.items() if eid.startswith('city_')]
    print(f'=== after founding (turn {info.get("turn")}): own cities={len(cities)} '
          f'{[(e.entity_id, round(e.dof_count, 3)) for e in cities]}')

    if not cities:
        print('    no city appeared within the budget — nothing to reconcile')
        env.close()
        return

    city_id = cities[0].entity_id.split('_')[1]
    city_obs = {str(k): v for k, v in as_dict(obs.get('city')).items()}.get(city_id, {})
    observed = cities[0].dof_count
    print(f'    city_{city_id} parameters: size={city_obs.get("size")} '
          f'food_stock={city_obs.get("food_stock")}/{city_obs.get("granary_size")} '
          f'improvements={sum(1 for v in as_list(city_obs.get("improvements")) if v)} '
          f'surplus=(f{city_obs.get("surplus_food")},s{city_obs.get("surplus_shield")},'
          f't{city_obs.get("surplus_trade")}) '
          f'aux_corruption={city_obs.get("city_corruption")}')
    print(f'    units as options: '
          + ', '.join(f'{e.entity_id}={e.dof_count:.2f}'
                      for eid, e in after.state.entities.items()
                      if eid.startswith('unit_'))[:200])

    # The prediction/observation pair: the model's belief vs the real city.
    model.record_pair('new_city_options', predicted=predicted_new_city,
                      observed=observed, turn=info.get('turn', 0))
    error = observed - predicted_new_city
    print(f'=== first prediction/observation pair (for statistical refinement)')
    print(f'    predicted={predicted_new_city:.3f}  observed={observed:.3f}  '
          f'error={error:+.3f} options '
          f'({(error / max(predicted_new_city, 1e-9)) * 100:+.1f}%)')
    print(f'    pairs recorded for new_city_options: '
          f'{model.stat_pairs("new_city_options")} (fit needs more than a single one)')

    print(f'=== reconciliation this run: {model.summary()["verdicts"]}')
    for rec in model.reconciliations:
        if rec.key.startswith('city.'):
            print(f'    {rec.verdict:<10} {rec.key:<28} model={rec.prior!r} '
                  f'world={rec.observed!r}  [{rec.evidence}]')

    env.close()


if __name__ == '__main__':
    main()
