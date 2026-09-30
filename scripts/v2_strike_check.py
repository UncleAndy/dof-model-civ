"""Проверка цены ответного удара: до 5 боёв цены нет, после — считается по измеренным исходам.

Проверка СИНТЕТИЧЕСКАЯ (названа так и есть): боевой юнит и бой воспроизводятся правкой реального
наблюдения. Это проверка МЕХАНИЗМА, а не измерение мира.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import calculus, generator, knowledge, sensors, threat  # noqa: E402

cap = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json")
d = json.loads(cap.read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
base_menu = sensors.read_menu(available)

g = knowledge.build_graph(obs, available, own_id=own_id, turn=1)
me = next(e for e in g.by_kind("unit") if e.is_own and e.attrs.get("x") is not None)
mx, my = me.attrs["x"], me.attrs["y"]
print(f"наш юнит {me.eid} в ({mx},{my}), атака типа = {me.attrs.get('type_attack_strength')}")

# 1) делаем юнита способным бить и добавляем чужого вплотную
me.attrs["type_attack_strength"] = 1
foe = knowledge.Entity(eid=f"unit:1@{mx + 1},{my}", kind="unit", owner=1, is_own=False,
                       name=None, attrs={"x": mx + 1, "y": my, "type_attack_strength": 1,
                                         "type_move_rate": 3, "виден_наблюдение": g.observations})
g.add_entity(foe)

print("\n== до нападения ==")
print("  угроз:", len(threat.threats(g)))
paths, _ = generator.generate(g, base_menu, own_id=own_id, avoid=wedges.is_wedged)
print("  цели strike:", sum(1 for p in paths if p.goal == "strike"))

# 2) наблюдаем нападение -> источник коллапса
g.mark_collapse_source(foe.eid, 1, 1, "нападение наблюдено (синтетическая проверка)")
tw = threat.STRIKE_TURNS
print("\n== после наблюдённого нападения ==")
print("  угроз:", [t["eid"] for t in threat.threats(g)])
price, who = threat.source_price(g, foe.eid, calculus.dof_of, tw)
print(f"  риск, который держит источник: {price:.3f} ({who})")

# варианты атаки мир в этом срезе не предлагал, поэтому подставляем законные направления
# меню в том же виде, что отдаёт мир: секция -> актор(str) -> {действие: разрешено}
_menu_unit = dict(base_menu.get("unit") or {})
_aid = me.eid.split(":")[1]
_opts = dict(_menu_unit.get(_aid) or {})
for _i in range(8):
    _opts[f"attack_{_i}"] = True
_menu_unit[_aid] = _opts
menu = dict(base_menu)
menu["unit"] = _menu_unit

paths, _ = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
strike = [p for p in paths if p.goal == "strike"]
print("  цели strike:", len(strike), "| шаг:", strike[0].steps[0].action if strike else None)

print("\n== цена удара при 0 боях (порог " + str(calculus.MIN_FIGHTS) + ") ==")
r0 = calculus._option_net(g, None, "unit", "attack_0", actor=me.eid.split(":")[1], depth=1)
print(f"  net={r0['net_delta']} | {r0['why']}")

for i in range(5):
    g.note_observation("бой", {"ход": 2 + i, "действие": "attack_0", "чужой_исчез": 1})
print("\n== цена удара после 5 боёв (все выиграны) ==")
st = g.fight_stats()
print("  статистика боёв:", st)
for a in ("attack_0", "attack_4"):
    r = calculus._option_net(g, None, "unit", a, actor=me.eid.split(":")[1], depth=1)
    print(f"  {a}: net={r['net_delta']} | {r['why']}")

print("\n== если бои проиграны нами (5 из 5: потерян наш юнит) ==")
g.observed["бой"] = [{"ход": 2 + i, "наш_потерян": 1} for i in range(5)]
r = calculus._option_net(g, None, "unit", "attack_4", actor=me.eid.split(":")[1], depth=1)
print(f"  attack_4: net={r['net_delta']} | {r['why']}")