"""Что есть в данных для двух пробелов: DoF улучшений и цена ответа на угрозу.

1) Улучшения: публикует ли мир список построек города (чтобы сравнить «с улучшением / без») и
   что лежит в записи города.
2) Защита: что записано про `unit/fortify` и про бои (есть ли признак «наш юнит укреплён»).
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402

# --- 1. поля записи города в сохранённом наблюдении ---
fixture = pathlib.Path("tests/fixtures/real_obs_01.json")
if fixture.exists():
    data = json.loads(fixture.read_text())
    if isinstance(data, list) and data:
        obs = data[0].get("observation") or {}
        cities = obs.get("city") or {}
        if cities:
            cid, c = next(iter(cities.items()))
            print(f"поля города {cid} ({len(c)} шт.):")
            for k in sorted(c):
                v = c[k]
                shown = f"len={len(v)}" if isinstance(v, (list, dict)) else str(v)[:60]
                print(f"   {k}: {shown}")

# --- 2. граф: эффекты и наблюдения про защиту ---
g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world.json")
print("\nэффект unit/fortify:", json.dumps(g.effect_of("unit", "fortify") or {}, ensure_ascii=False)[:500])
print("\nэффект unit/attack:", json.dumps(g.effect_of("unit", "attack") or {}, ensure_ascii=False)[:500])
print("\nбои (observed['бой']):")
for r in (g.observed.get("бой") or [])[-5:]:
    print("  ", json.dumps(r, ensure_ascii=False))
print("\nнападения (observed['нападение']):")
for r in (g.observed.get("нападение") or [])[-5:]:
    print("  ", json.dumps(r, ensure_ascii=False))
print("\nключи наблюдений:", sorted(g.observed.keys()))