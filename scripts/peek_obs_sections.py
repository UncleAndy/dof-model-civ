#!/usr/bin/env python
"""Ключи служебных разделов наблюдения: client / game / map / rules.

Зачем: гипотеза «наблюдение пустое из-за десинхрона клиента» проверяется полями
клиента, а «город снесён голодом» — полями города (surplus_food, food_stock).
Печатаю ровно то, что мир публикует.
"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/real_obs_01.json"
o = json.load(open(path))
if isinstance(o, list):
    o = o[0]
if "observation" in o and isinstance(o["observation"], dict):
    o = o["observation"]
for key in ("client", "game", "map", "rules", "options"):
    sec = o.get(key)
    if isinstance(sec, dict):
        print(f"── {key}: {sorted(sec.keys())}")
        print("   образец:", json.dumps(sec, ensure_ascii=False)[:400])
    else:
        print(f"── {key}: {type(sec).__name__} {json.dumps(sec, ensure_ascii=False)[:200]}")
city = o.get("city") or {}
for cid, rec in list(city.items())[:1]:
    keep = ("owner", "x", "y", "size", "food_stock", "surplus_food", "prod_food",
            "state", "turns_to_prod_complete", "production_kind", "production_value")
    print("── город", cid, {k: rec.get(k) for k in keep})