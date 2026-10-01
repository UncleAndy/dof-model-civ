"""Замер DoF города по накопленной базе знаний (числа для Andy, без правки кода).

Смотрим:
  * есть ли в графе сущности типа `city` и сколько у них возможных действий;
  * что записано в замерах города (`city_growth.jsonl`) и в трассах про меню города.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys

root = pathlib.Path("knowledge")
world = root / "world.json"
if not world.exists():
    sys.exit("нет knowledge/world.json")
data = json.loads(world.read_text())
print("верхние ключи world.json:", list(data.keys())[:8])

ents = data.get("сущности") or data.get("entities") or {}
if isinstance(ents, dict):
    items = list(ents.items())
else:
    items = [(e.get("id"), e) for e in ents]
cities = [(k, v) for k, v in items if "city" in str(k).lower() or (isinstance(v, dict) and "city" in str(v.get("тип", v.get("type", ""))).lower())]
print(f"всего сущностей: {len(items)}; похожих на город: {len(cities)}")
for k, v in cities[:6]:
    acts = (v or {}).get("действия") or (v or {}).get("actions") or []
    print(f"  {k}: тип={(v or {}).get('тип') or (v or {}).get('type')}; действий={len(acts)}"
          f"; ключи={list((v or {}).keys())[:8]}")

# замеры города
cg = root / "city_growth.jsonl"
if cg.exists():
    rows = [json.loads(l) for l in cg.read_text().splitlines() if l.strip()]
    print(f"\ncity_growth.jsonl: {len(rows)} записей; ключи: {list(rows[0].keys()) if rows else '-'}")
    for key in ("n_buildable", "buildable", "опций", "n_options"):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        if vals:
            print(f"  {key}: n={len(vals)}, медиана {statistics.median(vals)}, мин {min(vals)}, макс {max(vals)}")
    print("  пример:", json.dumps(rows[0], ensure_ascii=False)[:400])