#!/usr/bin/env python
"""Поля живого наблюдения: какие ключи вообще есть у города/юнита и сообщений.

Зачем: диагностика ранней потери города должна опираться на ПОЛЯ, которые мир
реально публикует, а не на те, которые я помню. Печатаю ключи и образец записи.
"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/real_obs_01.json"
o = json.load(open(path))
if isinstance(o, list):
    print("файл — список из", len(o), "записей; беру первую")
    o = o[0]
if "observation" in o and isinstance(o["observation"], dict):
    print("запись шага: turn", o.get("turn"), "-> беру observation")
    o = o["observation"]
print("верхние ключи:", sorted(o.keys()))
city = o.get("city") or {}
print("городов в наблюдении:", len(city))
for cid, rec in list(city.items())[:1]:
    print("город", cid, "ключи:", sorted(rec.keys()))
    print("образец:", json.dumps({k: rec[k] for k in list(rec)[:14]}, ensure_ascii=False)[:600])
unit = o.get("unit") or {}
print("юнитов:", len(unit))
for uid, rec in list(unit.items())[:1]:
    print("юнит", uid, "ключи:", sorted(rec.keys())[:30])
    print("образец:", json.dumps(rec, ensure_ascii=False)[:600])
for key in ("mini_game_messages", "messages", "turn_messages", "player"):
    if key in o:
        print(key, "->", json.dumps(o[key], ensure_ascii=False)[:400])