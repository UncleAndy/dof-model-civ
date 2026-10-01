"""Проверка цели `explore`: появляется ли путь движения и есть ли у него измеренная цена."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baselines import wedges  # noqa: E402
from brain.v2 import calculus, explore, generator, knowledge, sensors, threat  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_late_9000.json"
d = json.loads(Path(path).read_text())
obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
menu = sensors.read_menu(available)
g = knowledge.build_graph(obs, available, own_id=own_id, turn=d.get("turn") or 1)

rev = g.world.get("раскрытие") or []
print(f"карта {len(rev)}x{len(rev[0]) if rev else 0}; раскрыто "
      f"{sum(1 for c in rev for v in c if v)} клеток")

paths, _ = generator.generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
print("пути:", [(p.kind, p.goal, p.steps[0].action) for p in paths])
ex = [p for p in paths if p.goal == "explore"]
print("путей explore:", len(ex))

u = next((e for e in g.by_kind("unit") if e.is_own and e.attrs.get("x") is not None), None)
near = explore.unrevealed_near(g, u.attrs["x"], u.attrs["y"])
print(f"юнит {u.eid} в ({u.attrs['x']},{u.attrs['y']}); ближайшая нераскрытая: {near}")

print("\n== цена исследования без измерений ==")
g0, w0 = explore.explore_gain(g, "goto_4", u.eid.split(":")[1], calculus.dof_of,
                              lambda gg: calculus.impute(gg, "unit"))
print(f"  goto_4: {g0:.3f} | {w0}")

print("\n== после измерений (эффект goto + связь discovery) ==")
g.record_effect("unit", "goto", {"revealed_delta": 30}, {"действие": "goto_0"})
g.record_effect("unit", "goto", {"revealed_delta": 20}, {"действие": "goto_1"})
for i in range(10):
    g.note_observation("discovery", {"клеток": 5, "сущностей": 1})
print("  клеток/ход:", explore.tiles_per_move(g))
print("  сущностей/клетку:", explore.entities_per_tile(g))
for a in ("goto_0", "goto_4", "goto_6"):
    gg, ww = explore.explore_gain(g, a, u.eid.split(":")[1], calculus.dof_of,
                                  lambda x: calculus.impute(x, "unit"))
    print(f"  {a}: {gg:+.3f} | {ww[:120]}")

dec = calculus.evaluate(g, paths, own_id)
print("\nкандидаты:")
for c in dec.trace["candidates"][:6]:
    st = (c["path"].get("steps") or [{}])[0]
    print(f"  {c['path']['goal']}/{st.get('ctrl')}: net={c['net_delta']} | {str(c.get('why'))[:110]}")
print("выбрано:", dec.chosen.summary() if dec.chosen else None)
print("причина:", dec.trace["reason"])