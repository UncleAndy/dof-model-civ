"""Есть ли в наблюдении полный список типов с ценой (и где): правила, клиент, город."""
import json

d = json.load(open("/tmp/v2_late_9000.json"))
obs = d["observation"]
rules = obs.get("rules") or {}
print("ключи rules с unit/cost:", [k for k in rules if "unit" in k.lower() or "cost" in k.lower()])
c = (obs.get("city") or {}).get("121") or {}
cbu = c.get("can_build_unit")
print("can_build_unit: тип", type(cbu).__name__, "| истинных",
      sum(1 for v in (cbu if isinstance(cbu, list) else []) if v))
print("buy_cost:", c.get("buy_cost"), "| production_kind:", c.get("production_kind"),
      "| production_value:", c.get("production_value"))
print("improvements в городе:", json.dumps(c.get("improvements"), ensure_ascii=False)[:200])
print("\nсекции наблюдения:", sorted(obs.keys()))
cli = obs.get("client")
print("client:", json.dumps(cli, ensure_ascii=False)[:300])
opt = obs.get("options")
print("options:", json.dumps(opt, ensure_ascii=False)[:200])