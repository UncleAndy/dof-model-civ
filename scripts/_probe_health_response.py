"""Отклик модели на здоровье: что именно меняется при падении hp."""
from __future__ import annotations

import copy
import json
import pathlib

from env import entity_extractor as E
from env.config import HEALTH_COLLAPSE_RATIO, UNIT_HEALTH_W

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "real_obs_01.json"
KEYS = ("hp", "health", "hit_points", "hits")


def find_obs(node, depth=0):
    """Найти в захвате словарь наблюдения (в нём есть 'unit' или 'city')."""
    if depth > 4:
        return None
    if isinstance(node, dict):
        if "unit" in node or "city" in node:
            return node
        for val in node.values():
            found = find_obs(val, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for val in node[:20]:
            found = find_obs(val, depth + 1)
            if found:
                return found
    return None


def main() -> int:
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    steps = raw if isinstance(raw, list) else [raw]
    obs = {}
    for step in steps:
        cand = step.get("observation") if isinstance(step, dict) else None
        if isinstance(cand, dict) and (cand.get("unit") or cand.get("city")):
            obs = cand
            break
    if not obs:
        obs = find_obs(raw) or {}
    print("вид захвата:", type(raw).__name__,
          f"({len(raw)} шагов)" if isinstance(raw, (list, dict)) else "")
    print("верхние ключи наблюдения:", sorted(obs)[:14])
    units = E.as_dict(obs.get("unit"))
    print("юнитов в наблюдении:", len(units))
    uid, unit = next(((k, v) for k, v in units.items()
                      if isinstance(v, dict) and ("rule_name" in v or "type_hp" in v)),
                     (None, None))
    if unit is None:
        uid, unit = next(((k, v) for k, v in units.items() if isinstance(v, dict)),
                         (None, {}))
    if not unit:
        print("словаря состояния юнита в наблюдении нет — только маски действий")
        return 0
    print("взят юнит:", uid, "| тип:", unit.get("rule_name"),
          "| pop_cost:", unit.get("pop_cost"))
    print("поля здоровья в наблюдении:",
          {k: unit[k] for k in unit if any(s in k.lower() for s in KEYS)})
    print("HEALTH_COLLAPSE_RATIO =", HEALTH_COLLAPSE_RATIO,
          "| UNIT_HEALTH_W =", UNIT_HEALTH_W)
    _vals = E.default_model().values()
    print("носители считают здоровье в s_current:",
          _vals.get("POP_CARRIER_COUNTS_HEALTH_IN_CURRENT", "ключа нет"))
    print()

    hp_key = next((k for k in unit if any(s in k.lower() for s in KEYS)
                   and isinstance(unit[k], (int, float))), None)
    if hp_key is None:
        print("поля здоровья в наблюдении НЕТ — значит health_ratio падает на потолок")
        return 0
    full = unit[hp_key]
    print(f"ключ здоровья: {hp_key} = {full}; потолок type_hp =",
          unit.get("type_hp", "нет"))
    print()
    for carrier in (False, True):
        base = copy.deepcopy(unit)
        if carrier:
            base["pop_cost"] = 2
        print(f"── носитель населения: {carrier} (is_population_carrier="
              f"{E.is_population_carrier(base)}) ──")
        for hp in (full, full * 0.4, full * 0.1, 0):
            probe = copy.deepcopy(base)
            probe[hp_key] = hp
            hr = E.health_ratio(probe)
            opts, s_cur, s_fut = E.unit_options(probe)
            dof = min(1.0, opts / E.DOF_SCALE)
            gate = "ВОРОТА" if hr <= HEALTH_COLLAPSE_RATIO else "нет"
            print(f"   hp={hp:5.1f} hr={hr:5.3f} options={opts:8.4f} "
                  f"s_current={s_cur:7.4f} s_future={s_fut:7.4f} "
                  f"dof={dof:7.4f} ворота={gate}")
    return 0


raise SystemExit(main())
