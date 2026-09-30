"""В каких секциях наблюдения мир отдаёт ЧУЖИХ: unit / foreign_units / city / map.unit_owner."""
import json
import sys

d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json"))
obs = d["observation"]
own_id = d.get("my_id")
print("секции наблюдения:", sorted(obs.keys()))
for key in ("unit", "foreign_units", "city", "player"):
    sec = obs.get(key)
    if sec is None:
        print(f"\n{key}: секции нет")
        continue
    if isinstance(sec, dict):
        print(f"\n{key}: записей {len(sec)}")
        for k, v in list(sec.items())[:3]:
            print(f"   {k}: {json.dumps(v, ensure_ascii=False)[:220]}")
    else:
        print(f"\n{key}: {type(sec).__name__}")
m = obs.get("map") or {}
uo = m.get("unit_owner")
print("\nmap.unit_owner — есть:", uo is not None, "| тип:", type(uo).__name__)
if uo is not None:
    try:
        flat = [v for col in uo for v in (col if isinstance(col, list) else [col])]
        vals = {}
        for v in flat:
            vals[v] = vals.get(v, 0) + 1
        print("  распределение владельцев клеток с юнитами:", vals)
    except Exception as exc:  # noqa: BLE001
        print("  разобрать не удалось:", exc)