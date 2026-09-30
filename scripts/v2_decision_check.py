"""Почему выбрано то, что выбрано: полный разбор одного решения (оффлайн, на съёмке)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import calculus, generator, knowledge, sensors  # noqa: E402
from brain.v2.horizon import is_noop, research_gain, turns_to_tech  # noqa: E402

cap = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json")
store = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "knowledge" / "world.json"

d = json.loads(cap.read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
menu = sensors.read_menu(available)

g = knowledge.build_graph(obs, available, own_id=own_id)
if store.exists():
    prior = knowledge.KnowledgeGraph.load(store)
    g = knowledge.build_graph(obs, available, own_id=own_id, prior=prior)
    print(f"база знаний подгружена: {store}")

print("\n== игрок (опубликованные поля исследования) ==")
for e in g.by_kind("player"):
    if e.is_own:
        print("  ", {k: e.attrs.get(k) for k in ("researching", "research_name", "researching_cost",
                                                 "bulbs_researched", "science", "science_cost")})
print("  срок до технологии:", turns_to_tech(g))
print("  устав: base_tech_cost =", (g.rules or {}).get("base_tech_cost"))

print("\n== свои города ==")
for e in g.by_kind("city"):
    if e.is_own:
        print(f"  {e.eid} size={e.attrs.get('size')} DoF={e.dof}")

print("\n== эффекты в базе ==")
for k in ("tech/research_tech", "tech/set_tech_goal", "gov/set_sci_lux_tax", "turn/advance"):
    rec = g.effect_of(*k.split("/"))
    print(f"  {k}: {rec.get('change_counts') if rec else 'нет записи'}")

print("\n== канал tech: что предлагается и что отсеяно ==")
opts = sensors.valid_options(menu, "tech", "cur_player")
print("  всего законных:", len(opts))
noop = [o for o in opts if is_noop(g, o)]
print("  отсеяно как «ничего не меняет»:", noop)
for o in opts[:6]:
    gain, why = research_gain(g, o)
    print(f"  {o}: выигрыш {gain:+.3f} — {why}")

paths, open_goals = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
print(f"\n== путей {len(paths)} ==")
for p in paths:
    print("  ", p.summary())

dec = calculus.evaluate(g, paths, own_id)
print("\n== кандидаты решения ==")
for c in dec.trace["candidates"]:
    print(f"  {c['path']['goal']}/{c['path']['kind']} {c['path']['steps'][0]['action']}: "
          f"net={c['net_delta']} множитель={c.get('multiplier')} — {c['why']}")
print("\nвыбрано:", dec.chosen.summary() if dec.chosen else None)
print("причина:", dec.trace["reason"])
print("индекс:", dec.trace["index_current"], "| calc:", len(dec.trace["calc_included"]))