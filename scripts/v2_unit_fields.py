"""Какие поля мир реально отдаёт про юнита: свои и чужие. Нужно для цены угрозы."""
import json
import sys

d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json"))
obs = d["observation"]
own_id = d.get("my_id")
units = obs.get("unit") or {}
print(f"юнитов в наблюдении: {len(units)}, мой id = {own_id}")
own = [(k, v) for k, v in units.items() if v.get("owner") == own_id]
foreign = [(k, v) for k, v in units.items() if v.get("owner") != own_id]
print(f"своих: {len(own)}, чужих: {len(foreign)}")
for label, group in (("СВОЙ", own), ("ЧУЖОЙ", foreign)):
    if not group:
        print(f"\n{label}: нет")
        continue
    k, v = group[0]
    print(f"\n{label} {k}: ключи = {sorted(v.keys())}")
    print("  ", json.dumps(v, ensure_ascii=False)[:400])