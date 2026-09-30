"""Поля записи города и цена постройки: из чего можно ВЫВЕСТИ срок постройки."""
import json

d = json.load(open("/tmp/v2_late_9000.json"))
obs = d["observation"]
c = obs.get("city") or {}
for k, v in c.items():
    print("город", k, "| поля:", sorted(v.keys()))
    print("   производство/щиты:", {x: v.get(x) for x in v if "prod" in x or "shield" in x})
print()
for t in ("Warriors", "Settlers", "Barracks"):
    hit = None
    for tid, tech in (obs.get("tech") or {}).items():
        for u in (tech.get("sup_units") or []):
            nm = u.get("name") or u.get("rule_name")
            if nm == t:
                hit = {x: u.get(x) for x in ("name", "build_cost", "attack_strength",
                                             "defense_strength", "move_rate")}
        for im in (tech.get("sup_improvements") or []):
            nm = im.get("name") or im.get("rule_name")
            if nm == t and hit is None:
                hit = {x: im.get(x) for x in ("name", "build_cost")}
    print(f"{t}: {hit}")