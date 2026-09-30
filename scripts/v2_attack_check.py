"""Проверка правила «источник коллапса — только по наблюдённому нападению» (§10.33/§10.34).

Проверяются обе стороны правила:
  ДО нападения  — мирный чужой с атакой ПЛЮСУЕТСЯ в индекс, цены риска НЕТ, цели «выход» НЕТ;
  ПОСЛЕ нападения — атакующий становится источником коллапса, его возможности уходят из индекса,
  цена риска появляется, цель «выход» появляется, и держится 20 ходов.

Вторая половина проверки СИНТЕТИЧЕСКАЯ (названа так и есть): нападение воспроизводится правкой
реального наблюдения — убирается свой юнит и ставится чужой вплотную. Это проверка МЕХАНИЗМА,
а не измерение мира.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import attack, calculus, generator, knowledge, sensors, threat  # noqa: E402

cap = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_capture_seed9000.json")
d = json.loads(cap.read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
menu = sensors.read_menu(available)

g = knowledge.build_graph(obs, available, own_id=own_id, turn=1)
print("=== ДО нападения ===")
print("  угроз:", threat.threats(g), "| под ударом:", threat.exposure(g))
price, detail = threat.risk_price(g, calculus.dof_of, threat.STRIKE_TURNS)
print(f"  цена риска: {price} {detail}")
inc, exc = calculus.calc_set(g)
print(f"  в индексе сущностей: {len(inc)} (из них чужих: "
      f"{sum(1 for e in inc if not e['eid'].startswith(('unit:0', 'city:0', 'player:0')) and ':' in e['eid'])})")
s = calculus.index(g)
print(f"  индекс = {s['value']:.3f}")
paths, open_goals = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
print("  цели «выход»:", sum(1 for p in paths if p.goal == "escape"))

# --- синтетическое нападение: свой юнит пропал, чужой стоит вплотную ---
prev = attack.own_state(obs, own_id)
victim = next(iter(prev["units"]))
vx = prev["units"][victim]["x"]
vy = prev["units"][victim]["y"]
obs2 = json.loads(json.dumps(obs))
obs2["unit"].pop(victim, None)
uo = obs2["map"]["unit_owner"]
try:
    uo[vx + 1][vy] = 1
    where = f"({vx + 1},{vy})"
except (IndexError, TypeError):
    uo[vy][vx + 1] = 1
    where = f"({vy},{vx + 1})"
print(f"\n=== СИНТЕТИЧЕСКОЕ нападение: юнит {victim} пропал, чужой (владелец 1) в {where} ===")

g2 = knowledge.build_graph(obs2, available, own_id=own_id, prior=g, turn=2)
events, _st = attack.observe_slice(g2, obs2, own_id, 2, prev)
for ev in events:
    print("  событие:", json.dumps(ev, ensure_ascii=False))
print("  источники коллапса:", json.dumps(g2.collapse_sources(2), ensure_ascii=False))
print("  угрозы:", json.dumps(threat.threats(g2), ensure_ascii=False)[:300])

price2, detail2 = threat.risk_price(g2, calculus.dof_of, threat.STRIKE_TURNS)
print(f"  цена риска: {price2:.3f} {json.dumps(detail2, ensure_ascii=False)[:200]}")
inc2, exc2 = calculus.calc_set(g2)
print(f"  исключено как источник коллапса: "
      f"{[e['eid'] for e in exc2 if 'не наши' in str(e.get('why'))]}")
print(f"  индекс = {calculus.index(g2)['value']:.3f}")
menu2 = sensors.read_menu(available)
paths2, _ = generator.generate(g2, menu2, own_id=own_id, avoid=wedges.is_wedged)
print("  цели «выход»:", sum(1 for p in paths2 if p.goal == "escape"))

print("\n=== держится ли флаг горизонт (20 ходов) ===")
for t in (2, 21, 22, 25):
    print(f"  ход {t}: активных источников {len(g2.collapse_sources(t))}")