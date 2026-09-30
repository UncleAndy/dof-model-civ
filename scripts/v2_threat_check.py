"""Проверка цены угрозы на ЖИВОМ наблюдении с синтетически добавленной угрозой.

Настоящая угроза появляется поздно (контакт по замерам — на 27–69 ходу), поэтому механизм
проверяется так: берём реальное наблюдение, добавляем в граф чужой юнит с атакой вплотную к
нашему и смотрим, появится ли цена риска, путь выхода и выбор. Это синтетическая проверка
МЕХАНИЗМА, а не измерение мира — и она так и называется.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import calculus, generator, knowledge, sensors, threat  # noqa: E402
from brain.v2.horizon import tau as tau_window  # noqa: E402
from brain.v2.knowledge import Entity  # noqa: E402
from brain.v2.provenance import Value  # noqa: E402

cap = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json")
d = json.loads(cap.read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
menu = sensors.read_menu(available)

g = knowledge.build_graph(obs, available, own_id=own_id)
own_unit = next((e for e in g.by_kind("unit") if e.is_own and e.attrs.get("x") is not None), None)
if own_unit is None:
    print("своих юнитов с координатами нет")
    raise SystemExit(2)
ux, uy = own_unit.attrs["x"], own_unit.attrs["y"]
print(f"наш юнит {own_unit.eid} в ({ux},{uy})")

print("\n== до добавления угрозы ==")
tw, why = tau_window(g)
print(f"  τ = {tw:.1f} ({why})")
print("  угроз:", threat.threats(g), "| под ударом:", threat.exposure(g, tw))

# синтетическая угроза: чужой юнит с атакой вплотную
g.add_entity(Entity(eid="unit:999", kind="unit", owner=1, is_own=False, name="Warriors",
                    attrs={"x": ux + 1, "y": uy, "attack": 3, "defense": 2, "move_rate": 3},
                    dof=Value.inferred(5.0, 4.0, 6.0, source="аналогия:Warriors")))
print("\n== после добавления чужого Warriors (атака 3) в клетку рядом ==")
tw, why = tau_window(g)
print(f"  τ = {tw:.1f} ({why})")
print("  угроз:", threat.threats(g))
exp = threat.exposure(g, tw)
print("  под ударом:", exp)
price, detail = threat.risk_price(g, calculus.dof_of, tw)
print(f"  цена риска = {price:.3f}  {detail}")

paths, open_goals = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
print(f"\n== путей {len(paths)} ==")
for p in paths:
    print("  ", p.summary())

dec = calculus.evaluate(g, paths, own_id)
print("\n== кандидаты ==")
for c in dec.trace["candidates"]:
    st = (c["path"].get("steps") or [{}])[0]
    print(f"  {c['path']['goal']}: {st.get('action')} | net={c['net_delta']} | {c.get('why')}")
print("\nвыбрано:", dec.chosen.summary() if dec.chosen else None)
print("причина:", dec.trace["reason"])
print("риск в протоколе:", dec.trace.get("риск"))