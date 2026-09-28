#!/usr/bin/env python
"""Цена одного пункта содержания в ОПЦИЯХ города (§10.34, V3).

Правило проекта: параметр берётся из мира, а не подбирается. Здесь измеряется, на
сколько опций города меняет `+1` золота / щита / торговли / еды и `+1` жителя — на
РЕАЛЬНОЙ записи города из сохранённого наблюдения. Из этого получается честная цена
содержания юнита (`UNIT_UPKEEP_SINK_W`), а не подобранный вес.
"""
import json
import sys

from env.entity_extractor import city_options

path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/real_obs_01.json"
raw = json.load(open(path))
if isinstance(raw, list):
    raw = raw[0]
if "observation" in raw:
    raw = raw["observation"]
cities = raw.get("city") or {}
cid, rec = next(iter(cities.items()))
print(f"город {cid}: размер {rec.get('size')}, prod_food {rec.get('prod_food')}, "
      f"prod_shield {rec.get('prod_shield')}, prod_trade {rec.get('prod_trade')}, "
      f"surplus_gold {rec.get('surplus_gold')}, surplus_shield "
      f"{rec.get('surplus_shield')}, surplus_trade {rec.get('surplus_trade')}")
base = float(city_options(rec, model=None))
print(f"опций города (база): {base:.4f}")
for field in ("surplus_gold", "surplus_shield", "surplus_trade", "surplus_food",
              "prod_gold", "prod_shield", "prod_trade", "prod_food", "size"):
    if rec.get(field) is None:
        print(f"  {field}: нет в записи")
        continue
    shifted = dict(rec)
    shifted[field] = float(rec[field]) + 1.0
    try:
        after = float(city_options(shifted, model=None))
    except Exception as exc:  # noqa: BLE001
        print(f"  {field}: ошибка {type(exc).__name__}")
        continue
    print(f"  +1 {field}: опций {after:.4f} (Δ {after - base:+.4f})")