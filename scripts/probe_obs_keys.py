"""Точечные факты наблюдения: размеры карты, число игроков, видимость чужих юнитов, состав города."""
import json, sys

p = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/real_obs_01.json"
with open(p) as f:
    data = json.load(f)

rec = data[0]["observation"]

# --- карта: размеры из массивов ---
m = rec["map"]
terr = m["terrain"]
print("map.terrain: rows =", len(terr), "cols =", len(terr[0]))
print("map arrays:", {k: (len(v), len(v[0]) if v and hasattr(v[0], '__len__') else None) for k, v in m.items()})
print("map keys:", list(m.keys()))

# --- игроки ---
pl = rec["player"]
print("\nplayers:", len(pl), "ids:", sorted(pl.keys()))
for k, v in pl.items():
    print(f"  {k}: name={v.get('name')!r} alive={v.get('is_alive')} score={v.get('score')} nation={v.get('nation')}")

# --- правила, которые нужны для tau ---
r = rec["rules"]
for k in ["aifill", "citymindist", "food_cost", "base_tech_cost", "fogofwar", "xsize", "ysize", "mapseed", "onsetbarbs", "barbarianrate", "tech_cost_style"]:
    if k in r:
        print(f"  rules[{k}] = {r[k]}")

# --- чужие юниты во всех срезах ---
print("\n== unit dicts по срезам (owner -> count) ==")
for i, d in enumerate(data):
    o = d["observation"]
    units = o.get("unit", {})
    owners = {}
    types = {}
    for uid, u in units.items():
        owners[u.get("owner")] = owners.get(u.get("owner"), 0) + 1
        types[u.get("type_rule_name")] = types.get(u.get("type_rule_name"), 0) + 1
    print(f"  шаг {i}: turn={d.get('turn')} units={len(units)} owners={owners} types={types}")

# --- город: полный набор ключей ---
c = rec["city"]
cid = list(c.keys())[0]
print("\n== city keys ==")
for k, v in c[cid].items():
    vs = str(v)
    print(f"  {k}: {vs[:110]}")

# --- есть ли у чужих юнитов type_* поля (если чужие видны) ---
print("\n== sample foreign unit (owner != 0), если есть ==")
found = False
for d in data:
    for uid, u in d["observation"].get("unit", {}).items():
        if u.get("owner") != 0:
            print(f"  uid={uid}", json.dumps(u, ensure_ascii=False)[:600])
            found = True
            break
    if found:
        break
if not found:
    print("  чужих юнитов в этих 10 срезах нет")