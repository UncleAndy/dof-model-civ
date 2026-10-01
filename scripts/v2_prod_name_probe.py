"""Есть ли в наблюдении таблица «код постройки → имя» (чтобы не писать «код6»)."""
from __future__ import annotations

import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/real_obs_01.json")
data = json.loads(path.read_text())
obs = (data[0].get("observation") if isinstance(data, list) else data) or {}
print("секции наблюдения:", sorted(obs.keys()))
rules = obs.get("rules") or {}
print("rules:", type(rules).__name__, list(rules)[:12] if isinstance(rules, dict) else "")
if isinstance(rules, dict):
    for k, v in list(rules.items())[:8]:
        if isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"  rules[{k}]: {len(v)} записей; поля примера: {sorted(v[0].keys())[:12]}")
        elif isinstance(v, dict):
            print(f"  rules[{k}]: dict, ключи {list(v)[:8]}")
        else:
            print(f"  rules[{k}]: {str(v)[:80]}")
# в записи города: код и значение производства
cities = obs.get("city") or {}
if cities:
    c = next(iter(cities.values()))
    print(f"\nгород: production_kind={c.get('production_kind')} production_value={c.get('production_value')}"
          f" can_build_unit: len={len(c.get('can_build_unit') or [])}")
# есть ли где-то имена типов юнитов с id
units = obs.get("unit") or {}
if units:
    u = next(iter(units.values()))
    print("поля юнита:", sorted(u.keys()))
    print("пример:", {k: u[k] for k in list(u)[:8]})