"""Проверка: срок постройки и проба по варианту.

1) выводится ли срок из измеренной цены и щитов;
2) берёт ли проба вариант `produce_*`, чей срок неизвестен, даже когда эффект семейства уже
   наблюдён (иначе военный юнит не пробуется никогда).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import calculus, generator, horizon, knowledge, sensors  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_late_9000.json"
d = json.loads(Path(path).read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
menu = sensors.read_menu(available)
g = knowledge.build_graph(obs, available, own_id=own_id, turn=d.get("turn") or 1)

print("цены известных типов:", {e.name: e.attrs.get("build_cost")
                               for e in g.by_kind("unit_type") if e.attrs.get("build_cost")})
print("щиты города:", [(e.eid, e.attrs.get("prod_shield"), e.attrs.get("shield_stock"),
                        e.attrs.get("turns_to_prod_complete")) for e in g.by_kind("city")
                       if e.is_own])

for act in ("produce_Warriors", "produce_Settlers", "produce_Barracks"):
    eta, src = horizon._measured_eta(g, act[len("produce_"):])
    if eta is None:
        eta, src = horizon._published_eta(g)
    if eta is None:
        eta, src = horizon._derived_eta(g, act[len("produce_"):])
    gain, why = horizon.production_gain(g, act)
    print(f"  {act}: срок={eta} ({src or 'нет'}) | gain={gain:.3f} | {why[:110]}")

print("\n== проба, когда эффект `produce` уже наблюдён ==")
g.record_effect("city", "produce", {"city_shields_changed": 3}, {"действие": "produce_Barracks"})
p = generator._path_probe(g, menu)
print("  выбрана проба:", p.steps[0].action if p else None,
      "| почему:", (p.source if p else ""))
print("  срок Warriors известен?", generator._eta_known(g, "produce_Warriors"))
print("  срок Settlers известен?", generator._eta_known(g, "produce_Settlers"))

print("\n== среднее по измеренным + разрешение ничьей ==")
for variant, eta in (("Coinage", 8), ("Barracks", 12)):
    g.note_observation("produce_eta", {"вариант": variant, "значение": eta})
for act in ("produce_Warriors", "produce_Settlers", "produce_Barracks", "produce_Coinage"):
    eta, src = horizon.eta_of(g, act[len("produce_"):])
    gain, why = horizon.production_gain(g, act)
    print(f"  {act}: срок={eta} ({src}) | gain={gain:.3f}")
_paths, _ = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
_kp = [x for x in _paths if x.steps[0].ctrl == "city"]
if _kp:
    _alts = _kp[0].steps[0].alternatives or []
    _kg, _kg_why = calculus.knowledge_gain(g, _alts)
    print(f"  цена незнания: {_kg:.3f} ({_kg_why})")

_paths, _ = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
dec = calculus.evaluate(g, _paths, own_id)
for c in dec.trace["candidates"]:
    st = (c["path"].get("steps") or [{}])[0]
    if st.get("ctrl") == "city":
        print(f"  канал города: выбран вариант {c.get('лучший_вариант')} (net {c['net_delta']})")
        print(f"    почему: {str(c.get('why'))[:130]}")
