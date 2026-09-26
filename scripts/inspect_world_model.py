"""First run of the world-model refinement loop against the live stand.

Extracts one real turn (which triggers the reconciliation pass) and reports how
far the pre-installed model agrees with the world: confirmed claims, corrections,
new facts learned, and anything the model could not check.

Usage: .venv/bin/python scripts/inspect_world_model.py [--turns 1]
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings('ignore')
os.environ['PYTHONWARNINGS'] = 'ignore'

_p = argparse.ArgumentParser()
_p.add_argument('--turns', type=int, default=2)
_ARGS, _rest = _p.parse_known_args()
sys.argv = [sys.argv[0]] + _rest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports

from env.entity_extractor import GameStateExtractor
from env.world_model import Provenance


def main() -> None:
    fc_args['port'] = Ports.get()
    env = gymnasium.make('civrealm/FreecivBase-v0', client_port=fc_args['port'])
    obs, info = env.reset()
    extractor = GameStateExtractor(my_player_id=0)
    try:
        extractor.my_player_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        pass

    for _ in range(_ARGS.turns):
        turn = info.get('turn', 0)
        extractor.extract(obs, info, turn)
        obs, _r, terminated, truncated, info = env.step(None)  # end the turn
        if terminated or truncated:
            break

    model = extractor.model
    print(f'\n=== turn {info.get("turn")} | model entries: {len(model.entries)}')
    summary = model.summary()
    print(f'    by provenance: {summary["entries_by_source"]}')
    print(f'    reconciliations: {summary["reconciliations"]}  {summary["verdicts"]}')
    print(f'    corrections applied: {summary["corrections"]}')

    checked = [r for r in model.reconciliations if r.verdict in ('match', 'corrected')]
    print(f'\n=== claims the world was asked about ({len(checked)})')
    seen: dict[str, str] = {}
    for rec in model.reconciliations:
        seen.setdefault(rec.key, rec.verdict)
    for key, verdict in sorted(seen.items()):
        rec = next(r for r in model.reconciliations if r.key == key)
        print(f'    {verdict:<10} {key:<44} model={rec.prior!r:<12} world={rec.observed!r}'
              + (f'   [{rec.evidence}]' if rec.evidence else ''))

    new_facts = [r for r in model.reconciliations if r.verdict == 'new']
    print(f'\n=== new facts learned from the world: {len(new_facts)}')
    by_type: dict[str, int] = {}
    for rec in new_facts:
        specimen = rec.key.split('.')[1] if rec.key.startswith('unit_type.') else 'other'
        by_type[specimen] = by_type.get(specimen, 0) + 1
    for specimen, count in sorted(by_type.items()):
        sample = [r for r in new_facts if f'unit_type.{specimen}.' in r.key][:4]
        detail = ', '.join(f'{r.key.rsplit(".", 1)[1]}={r.observed!r}' for r in sample)
        print(f'    {specimen:<12} {count:>3} facts   e.g. {detail}')

    print('\n=== reality check')
    print(f'    entries whose provenance is the model\'s own assumption: '
          f'{summary["entries_by_source"].get(Provenance.ASSUMED.value, 0)}')
    if summary['corrections']:
        print('    corrections:')
        for entry in model.corrections():
            last = entry.history[-1]
            print(f'      {entry.key}: {last["old"]!r} -> {last["new"]!r} '
                  f'(turn {last["turn"]}, {last["evidence"]})')
    else:
        print('    no corrections — the pre-installed model agrees with this stand '
              'on every rule it claims')

    env.close()


if __name__ == '__main__':
    main()
