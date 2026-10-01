"""Синтетическая проверка пути «бой, начатый врагом» — того, что уронил прогон A.

Воспроизводим ровно ту ситуацию: наш юнит был ранен на клетке, рядом стоял видимый чужой.
Проверяем, что запись боя получается ПОЛНОЙ (наш_укреплён, наш_до, наш_хп_до, чужой_атака) и что
вызов не падает — именно на этом падал `attack_of` с лишним аргументом.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.v2 import attack as attack_mod  # noqa: E402
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402

g = KnowledgeGraph()
g.world = {"xsize": 20, "ysize": 20}
# наш юнит и его тип (чтобы было откуда взять защиту)
g.ensure("unit:5", "unit", owner=0, is_own=True, name="Warriors")
g.entity("unit:5").attrs.update({"x": 5, "y": 5, "type_defense_strength": 2})
g.ensure("unit_type:Warriors", "unit_type", name="Warriors")
g.entity("unit_type:Warriors").attrs.update({"dof_families": 6, "attack_strength": 3})

obs = {
    "map": {"unit_owner": [[255] * 20 for _ in range(20)], "terrain": [[0] * 20 for _ in range(20)]},
    "unit": {"5": {"owner": 0, "type_rule_name": "Warriors", "x": 5, "y": 5, "health": 10,
                   "moves_left": 0, "type_defense_strength": 2}},
    "city": {},
}
obs["map"]["unit_owner"][5][6] = 3          # чужой вплотную (x=5, y=6)

prev = {"units": {"5": {"x": 5, "y": 5, "health": 20}}, "cities": {}, "foe": {}}
events, now = attack_mod.observe_slice(g, obs, own_id=0, turn=5, prev=prev, last_choice=None)

print(f"событий: {len(events)}")
for ev in events:
    print("  событие:", ev)
fights = [r for r in (g.observed.get("бой") or []) if isinstance(r, dict)]
print(f"\nзаписей боя: {len(fights)}")
for f in fights:
    print("  бой:", f)
required = {"наш_укреплён", "наш_до", "наш_хп_до", "чужой_атака"}
ok = fights and required.issubset(fights[-1].keys())
print("\nПРОВЕРКА:", "запись боя полная — путь работает" if ok
      else "запись неполная или боя не было — путь НЕ подтверждён")
raise SystemExit(0 if ok else 1)