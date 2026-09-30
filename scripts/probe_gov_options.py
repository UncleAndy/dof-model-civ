"""Что именно мир предлагает: словарь переходов из живой съёмки (меню, только valid)."""
import json
from collections import Counter
from pathlib import Path

p = Path("/tmp/v2_capture_seed9000.json")
d = json.loads(p.read_text())
av = d["available_actions"]

def valid(section, actor):
    return sorted(a for a, ok in (av.get(section, {}).get(actor, {}) or {}).items() if ok)

print("== gov: все разрешённые переходы ==")
for a in valid("gov", "0"):
    print("  ", a)
tax = [a for a in valid("gov", "0") if a.startswith("set_sci_lux_tax")]
gov = [a for a in valid("gov", "0") if a.startswith("change_gov")]
print(f"  ИТОГО: ставки налог/наука/роскошь = {len(tax)}, смена правительства = {len(gov)}")

print("\n== tech: разрешённые (первые 20 из 87) ==")
t = valid("tech", "cur_player")
print("  ", t[:20])
print("  всего:", len(t), "| из них research_*:", sum(1 for x in t if x.startswith("research_tech")),
      "| set_tech_goal_*:", sum(1 for x in t if x.startswith("set_tech_goal")))

print("\n== unit 101 (Settlers): разрешённые переходы ==")
u = valid("unit", "101")
print("  ", u)
print("  всего:", len(u))
print("\n== unit 108 (Explorer) ==")
u2 = valid("unit", "108")
print("  ", u2, "| всего:", len(u2))

print("\n== частоты имён действий по всем акторам (шаблон -> сколько раз) ==")
cnt = Counter()
for section, actors in av.items():
    for actor, actions in actors.items():
        for a, ok in actions.items():
            if ok:
                base = a.split("_")[0]
                cnt[f"{section}/{base}"] += 1
for k, v in cnt.most_common(25):
    print(f"  {k}: {v}")