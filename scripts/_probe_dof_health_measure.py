"""Отклик новой меры: DoF сущности через настоящий путь извлечения."""
from __future__ import annotations

import copy
import inspect
import json
import pathlib

from env.entity_extractor import GameStateExtractor, as_dict, health_ratio

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "real_obs_01.json"
KEYS = ("health", "hp", "hit_points")


def main() -> int:
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    steps = raw if isinstance(raw, list) else [raw]
    obs = {}
    chosen = {}
    for step in steps:
        cand = step.get("observation") if isinstance(step, dict) else None
        if isinstance(cand, dict) and cand.get("unit"):
            obs = cand
            chosen = step if isinstance(step, dict) else {}
            break
    units = as_dict(obs.get("unit"))
    uid, unit = next(((k, v) for k, v in units.items()
                      if isinstance(v, dict) and "health" in v), (None, None))
    if unit is None:
        print("юнита со здоровьем в наблюдении нет")
        return 0
    extr = GameStateExtractor()
    print("подпись extract:", inspect.signature(extr.extract))
    print("юнит:", uid, "| health =", unit.get("health"), "| type_hp =",
          unit.get("type_hp"))
    print()
    print(f"{'health':>8} {'hr':>7} {'DoF':>9} {'options':>10} {'в наборе':>9}")
    for health in (unit.get("health"), 8, 2, 0):
        probe = copy.deepcopy(obs)
        probe["unit"] = dict(units)
        probe["unit"][uid] = dict(unit, health=health)
        state = extr.extract(probe, chosen.get("info") or {},
                             int(chosen.get("turn") or 1))
        matrix = getattr(state, "state", state)
        ents = getattr(matrix, "entities", None) or {}
        ent = ents.get(f"unit_{uid}")
        hr = health_ratio(probe["unit"][uid])
        if ent is None:
            print(f"{health:>8} {hr:>7.3f} {'нет сущности':>9}")
            continue
        dof = ent.current_dof if hasattr(ent, "current_dof") else ent["current_dof"]
        opts = (ent.dof_options if hasattr(ent, "dof_options") else None)
        print(f"{health:>8} {hr:>7.3f} {dof:>9.4f} "
              f"{(opts if opts is not None else float('nan')):>10.4f} "
              f"{str(f'unit_{uid}' in ents):>9}")
    return 0


raise SystemExit(main())
