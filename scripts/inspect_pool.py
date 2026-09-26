"""Live diagnosis: what the agent can actually do, and why it declines.

Prints, for one live state: the valid action pool per controller/actor and its
families, the DoF deltas the bridge projects for the generated candidates, the
shortlist handed to DOF-Core, and the core's own verdict (with the same scaled
penalty the tournament uses).

Usage: .venv/bin/python scripts/inspect_pool.py [--turns 1]
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

_p = argparse.ArgumentParser()
_p.add_argument("--turns", type=int, default=1)
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports

from env.config import AXIOM4_PENALTY_OPTIONS, CORE_DOF_SCALE
from env.entity_extractor import GameStateExtractor, as_dict, compute_total_dof_index
from env.action_mapper import ActionOptionGenerator
from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator

try:
    from dof_core import CoreAction, CoreEntity, DOFCalculusCore
    HAVE_CORE = True
except Exception:  # noqa: BLE001
    HAVE_CORE = False


def families(actions) -> Counter:
    out: Counter = Counter()
    for name in actions:
        parts = str(name).split('_')
        out['_'.join(parts[:2]) if len(parts) > 1 else str(name)] += 1
    return out


def main() -> None:
    fc_args['port'] = Ports.get()
    env = gymnasium.make('civrealm/FreecivBase-v0', client_port=fc_args['port'])
    obs, info = env.reset()
    extractor = GameStateExtractor(my_player_id=0)
    try:
        extractor.my_player_id = env.get_playerid()
        print(f'my_player_id = {extractor.my_player_id}')
    except Exception:  # noqa: BLE001
        pass
    mapper = ActionOptionGenerator()

    print('cities:', [(cid, c.get('owner'), c.get('name'))
                      for cid, c in as_dict(obs.get('city')).items()])
    print('unit owners:', sorted({u.get('owner') for u in as_dict(obs.get('unit')).values()}))
    print('players:', [(pid, p.get('name')) for pid, p in as_dict(obs.get('player')).items()])

    for turn in range(_ARGS.turns):
        avail = as_dict(info.get('available_actions'))
        print(f'=== turn {info.get("turn")}')
        for ctrl, actors in avail.items():
            for actor, acts in as_dict(actors).items():
                names = [n for n, p in as_dict(acts).items() if str(p) not in ('', '{}', 'False')]
                allnames = list(as_dict(acts).keys())
                print(f'  {ctrl}/{actor}: {len(allnames)} actions, {len(names)} valid')
                if names and ctrl != 'tech':
                    for fam, n in families(names).most_common(8):
                        print(f'      {fam:<30} {n}')

        dof = extractor.extract(obs, info, info.get('turn', 0))
        state = dof.state
        print(f'  state: {len(state.entities)} entities, index={compute_total_dof_index(state):.3f}, '
              f'new_city={state.bridge.new_city_options:.2f}, '
              f'tech_gains={len(state.bridge.tech_research_gain)}, '
              f'unit_types={len(state.bridge.unit_type_options)}')

        pool = mapper.generate_from_state(state, avail)
        fam = Counter()
        for c in pool:
            fam[(c['ctrl_type'], c['action_name'].split('_')[0])] += 1
        print(f'  pool: {len(pool)} candidates; families with projected delta:')
        best = sorted(pool, key=lambda c: -sum(c['projected_dof_delta'].values()))[:10]
        for c in best:
            gain = sum(c['projected_dof_delta'].values())
            print(f'      {c["ctrl_type"]}/{c["actor_id"]}/{c["action_name"]:<34} '
                  f'delta={gain:+.3f} rev={c["is_reversible"]}')

        gen = HeuristicGenerator(strategy=DEFENSIVE)
        gen.max_candidates = 8
        shortlist = gen.generate_candidates(state, avail)
        print(f'  shortlist ({len(shortlist)}): '
              + ', '.join(f'{c["action_name"]}({sum(c["projected_dof_delta"].values()):+.2f})'
                          for c in shortlist))

        if HAVE_CORE and shortlist:
            core = DOFCalculusCore(lookahead_horizon=3,
                                   context_switch_penalty=AXIOM4_PENALTY_OPTIONS)
            entities = [CoreEntity(entity_id=e.entity_id, current_dof=e.dof_count,
                                   is_collapse_source=e.is_collapse_source,
                                   is_reversible=e.time_to_collapse_mks > 1e14)
                        for e in state.entities.values()]
            actions = [CoreAction(action_id=c['option_id'], description='',
                                  dof_delta=list(c['projected_dof_delta'].items()),
                                  is_reversible=bool(c['is_reversible']),
                                  duration_turns=1.0)
                       for c in shortlist]
            decision = core.select_best(entities, actions)
            print(f'  core: chosen={decision.chosen_action_id} net={decision.net_delta:+.4f} '
                  f'root={decision.root_index:.3f}')
            for aid, net, vetoed in decision.audit:
                print(f'      {net:+.4f} vetoed={vetoed} {aid}')

        break  # one decision cycle is enough to diagnose

    env.close()


if __name__ == '__main__':
    main()
