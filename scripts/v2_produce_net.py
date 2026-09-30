"""Какие варианты производства рассматриваются и как они оценены (на позднем снимке)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import calculus, families, generator, knowledge, sensors  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_late_9000.json"
d = json.loads(Path(path).read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
menu = sensors.read_menu(available)
print("город в срезе:", len(obs.get("city") or {}), "| ход:", d.get("turn"))

g = knowledge.build_graph(obs, available, own_id=own_id, turn=d.get("turn") or 1)
paths, open_goals = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
print("путей:", len(paths), [(p.kind, p.goal) for p in paths])

citypaths = [p for p in paths if p.steps[0].ctrl == "city"]
if not citypaths:
    print("канала города в коридоре нет")
for p in citypaths:
    st = p.steps[0]
    print(f"\nканал города, актор {st.actor}, вариантов {len(st.alternatives or [])}")
    for a in (st.alternatives or []):
        fam = families.action_family(a)
        r = calculus._option_net(g, None, "city", a, actor=st.actor, depth=len(p.steps))
        if fam == "produce" or "warrior" in str(a).lower() or "barracks" in str(a).lower():
            print(f"  {a:26s} fam={fam:16s} net={r['net_delta']} | {str(r['why'])[:90]}")

print("\nвсе семейства вариантов канала города:")
seen = {}
for p in citypaths:
    for a in (p.steps[0].alternatives or []):
        fam = families.action_family(a)
        seen.setdefault(fam, []).append(a)
for fam, names in sorted(seen.items()):
    print(f"  {fam}: {len(names)} (напр. {names[0]})")