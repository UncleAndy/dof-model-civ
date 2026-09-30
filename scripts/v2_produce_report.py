"""Почему канал города не выбирает производство (`produce_*`): смотрим net по вариантам."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import calculus, families, generator, knowledge, sensors  # noqa: E402

cap = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json")
d = json.loads(cap.read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
menu = sensors.read_menu(available)

g = knowledge.build_graph(obs, available, own_id=own_id, turn=1)
paths, open_goals = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
print(f"путей: {len(paths)}; цели без пути: {len(open_goals)}")
for p in paths:
    st = p.steps[0]
    print(f"  [{p.kind}/{p.goal}] {st.ctrl}/{st.actor}/{st.action} "
          f"(вариантов {len(st.alternatives or [])})")

dec = calculus.evaluate(g, paths, own_id)
print("\nкандидаты:")
for c in dec.trace["candidates"]:
    p = c["path"]
    print(f"  {p['goal']}: net={c['net_delta']} | {str(c.get('why'))[:110]}")

print("\nвсе варианты каналов по семействам:")
for p in paths:
    if p.kind != "путь" and p.steps[0].ctrl != "city":
        continue
    st = p.steps[0]
    for a in (st.alternatives or [])[:80]:
        fam = families.action_family(a)
        r = calculus._option_net(g, None, st.ctrl, a, actor=st.actor, depth=len(p.steps))
        if fam in ("produce", "city_work", "city_unwork", "city_buy_production"):
            print(f"  {a:28s} fam={fam:18s} net={r['net_delta']} | {str(r['why'])[:80]}")