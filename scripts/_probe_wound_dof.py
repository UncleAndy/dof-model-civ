"""Проверка посылки (б): понижает ли удар по нашей сущности её ИЗМЕРЕННЫЙ DoF.

Считаем не мнение: берём запись партии §13.85 и смотрим, что стало с DoF нашего юнита
и с индексом вокруг хода 96 (ранение health 10 → 4).
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE = ROOT / "knowledge" / "live_trace_9570_port6003.jsonl"
UNIT = "unit_111"
LO, HI = 93, 98


def main() -> int:
    rows = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    first = next((row for row in rows if row.get("разбивка")), None)
    items = (first or {}).get("разбивка") or []
    print("поля записи сущности в разбивке:", sorted(items[0].keys()) if items else "—")
    if items:
        print("пример:", json.dumps(items[0], ensure_ascii=False)[:220])
    print()
    prev_units: dict[str, float] = {}
    for row in rows:
        h = row.get("ход")
        if not isinstance(h, int) or not (LO <= h <= HI):
            continue
        items = row.get("разбивка") or []
        unit_dof = None
        cur: dict[str, float] = {}
        for item in items:
            eid = str(item.get("id"))
            val = item.get("DoF", item.get("dof", item.get("дof")))
            if isinstance(val, (int, float)):
                cur[eid] = float(val)
            if eid == UNIT:
                unit_dof = val
        print(f"ход {h}: индекс {row.get('индекс')}, сущностей {row.get('сущностей')}, "
              f"в наборе {row.get('в_расчёте')}; {UNIT} DoF={unit_dof}")
        if prev_units and cur:
            fell = {k: (prev_units[k], cur[k]) for k in cur
                    if k in prev_units and cur[k] < prev_units[k] - 1e-12}
            rose = {k: (prev_units[k], cur[k]) for k in cur
                    if k in prev_units and cur[k] > prev_units[k] + 1e-12}
            gone = sorted(set(prev_units) - set(cur))
            print(f"    против прошлого хода: упало {len(fell)} {list(fell.items())[:3]}, "
                  f"выросло {len(rose)}, исчезло {len(gone)} {gone[:4]}")
        prev_units = cur
    return 0


raise SystemExit(main())
