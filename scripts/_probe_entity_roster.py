"""Реестр сущностей состояния: кто сегодня считается (перед решением о чужом игроке)."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env.entity_extractor import GameStateExtractor   # noqa: E402


def pick(entity, key, default=0.0):
    if isinstance(entity, dict):
        return entity.get(key, default)
    return getattr(entity, key, default)


def roster(extr, obs, info, turn, label):
    state = extr.extract(obs, info, turn)
    matrix = getattr(state, "state", state)
    ents = getattr(matrix, "entities", None) or {}
    print(f"--- {label}: ход {turn}, сущностей {len(ents)}")
    for eid in sorted(ents):
        e = ents[eid]
        print(f"    {eid:<16} DoF {pick(e, 'current_dof'):>8.4f}  options "
              f"{pick(e, 'dof_options'):>8.4f}  known {pick(e, 'dof_known', True)}  "
              f"label {pick(e, 'is_collapse_source', False)}")
    units = [e for e in ents if str(e).startswith("unit_")]
    dipl = [e for e in ents if str(e).startswith("diplomacy_")]
    players = [e for e in ents if str(e).startswith("player_")]
    print(f"    (юнитов {len(units)}, дипломатий {len(dipl)}, игроков {len(players)})")


def main() -> int:
    extr = GameStateExtractor()
    fix = ROOT / "tests" / "fixtures" / "real_obs_01.json"
    steps = json.loads(fix.read_text(encoding="utf-8"))
    ok = [s for s in steps if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    last = ok[-1]
    roster(extr, last["observation"], last.get("info") or {}, int(last.get("turn") or 1),
           "фикстура")
    print()
    live = ROOT / "knowledge" / "live_trace_9570_port6003.jsonl"
    if not live.exists():
        print("живого захвата нет:", live)
        return 0
    rows = []
    for line in live.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("observation"), dict):
            rows.append(r)
    print("шагов с наблюдением:", len(rows))
    for r in rows:
        if int(r.get("turn") or 0) in (95, 96):
            roster(extr, r["observation"], r.get("info") or {}, int(r["turn"]),
                   "живой захват (§13.85: удар на 96)")
    return 0


raise SystemExit(main())
