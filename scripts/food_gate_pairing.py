#!/usr/bin/env python
"""Сверка решений Правила F с УШЕДШИМИ действиями: есть ли протечки.

Почему именно так: состояние внутри хода меняется от действия к действию, поэтому
сверка «по состоянию на начало хода» даёт ложные протечки (измерено: 167 ложных на
первой проверке). Правильная сверка — по журналу решений правила, где числа записаны
на МОМЕНТ решения.

Протечкой считается: в ходу ушло действие с именем X, а ВСЕ решения правила по имени X
в этом ходу были «запретить». Если по тому же имени было и разрешение (состояние успело
измениться — законный ход), это не протечка, и такие случаи считаются отдельно.
"""
import json
import sys
from collections import defaultdict

dump_path, gate_path = sys.argv[1], sys.argv[2]
offset = int(sys.argv[3]) if len(sys.argv) > 3 else 0
rows = [json.loads(x) for x in open(dump_path, encoding="utf-8") if x.strip()]
gate = [json.loads(x) for x in open(gate_path, encoding="utf-8") if x.strip()]

gate_by = defaultdict(lambda: defaultdict(list))   # (эпизод, ход, имя) -> [deny...]
for d in gate:
    turn = d.get("turn")
    turn = None if turn is None else int(turn) + offset
    gate_by[d.get("эпизод")][(turn, str(d.get("name")))].append(bool(d.get("deny")))

executed = defaultdict(int)
leaks = []
ambiguous = 0
unchecked = 0
for r in rows:
    ep, turn = r.get("эпизод"), r.get("turn")
    for a in r.get("действия_за_ход") or []:
        name = str(a[2]) if len(a) > 2 else ""
        if not (name.startswith("city_unwork_")
                or name.startswith("city_change_specialist")
                or name == "join_city"):
            continue
        executed[name.split("_")[0] + "_" + (name.split("_")[1] if name.startswith("city_") else "")] += 1
        verdicts = gate_by.get(ep, {}).get((turn, name))
        if not verdicts:
            unchecked += 1
            continue
        if all(verdicts):
            leaks.append((ep, turn, name, verdicts))
        elif any(verdicts):
            ambiguous += 1

print(f"срезов {len(rows)}, решений правила {len(gate)}")
print(f"выполнено действий трёх семейств: {sum(executed.values())} "
      f"({dict(executed)})")
print(f"ПРОТЕЧКИ (ушло при единогласном запрете): {len(leaks)}")
for leak in leaks[:10]:
    print("   протечка:", leak)
print(f"смешанные решения (было и разрешение) — законные: {ambiguous}; "
      f"без решения правила: {unchecked}")