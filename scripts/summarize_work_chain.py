#!/usr/bin/env python
"""Сводка замеров работ: превращения террейна, цепочка, достижимость.

Читает JSONL, который пишет `scripts/measure_work_chain.py`, и печатает три
таблицы. Никаких выводов «по одному наблюдению»: у каждой строки печатается
число наблюдений, и там, где их мало, это видно.

    python scripts/summarize_work_chain.py --in work_chain_measurements.jsonl
"""
import argparse
import json
from collections import Counter, defaultdict


def load(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="work_chain_measurements.jsonl")
    args = ap.parse_args()
    rows = load(args.src)
    print(f"строк: {len(rows)}")
    kinds = Counter(r.get("kind") for r in rows)
    print("по видам:", dict(kinds))
    print()

    # ── 1. Превращения террейна: до → после, с выходом результата ──────────
    print("=" * 84)
    print("1. ПРЕВРАЩЕНИЯ ТЕРРЕЙНА (работа меняет сам террейн)")
    print("=" * 84)
    transforms = defaultdict(list)
    for r in rows:
        if r.get("kind") != "watch" or not r.get("changed"):
            continue
        key = (r.get("action"),
               f"{r.get('terrain_before')}{'+' + ','.join(r.get('extras_before') or []) if r.get('extras_before') else ''}",
               f"{r.get('terrain')}{'+' + ','.join(r.get('extras') or []) if r.get('extras') else ''}")
        ob = r.get("output_before") or [0, 0, 0]
        oa = r.get("output") or [0, 0, 0]
        if len(ob) >= 3 and len(oa) >= 3:
            delta = tuple(oa[i] - ob[i] for i in range(3))
        else:
            delta = (0, 0, 0)
        transforms[key].append(delta)
    if not transforms:
        print("  нет завершённых превращений в этих данных")
    for (action, before, after), deltas in sorted(transforms.items()):
        n = len(deltas)
        mean = tuple(sum(d[i] for d in deltas) / n for i in range(3))
        print(f"  {action:<18} {before:<28} → {after:<28} "
              f"Δеда/щиты/торговля = {mean[0]:+.2f}/{mean[1]:+.2f}/{mean[2]:+.2f}  (n={n})")
    print()

    # ── 2. Цепочка: что стало валидным после завершения работы ─────────────
    print("=" * 84)
    print("2. ЦЕПОЧКА РАБОТ (валидность сообщает сервер, а не правила)")
    print("=" * 84)
    # Строгое различие: сравниваем валидный набор ДО работы (строка `start`) с
    # набором ПОСЛЕ её завершения. Печатать «после cultivate валидно plant» без
    # сравнения нельзя: plant мог быть валиден и раньше, тогда это не открытие.
    starts = {r.get("unit"): r for r in rows if r.get("kind") == "start"}
    finished = 0
    opened = Counter()
    closed = Counter()
    for r in rows:
        if r.get("kind") != "watch" or not r.get("changed"):
            continue
        st = starts.get(r.get("unit"))
        if not st:
            continue
        finished += 1
        before = set(st.get("valid_work") or [])
        after = set(r.get("valid_work_now") or [])
        for name in sorted(after - before):
            opened[(st.get("action"), name)] += 1
        for name in sorted(before - after):
            closed[(st.get("action"), name)] += 1
    if not finished:
        print("  нет завершённых работ с валидностью в этих данных")
    for (done, appeared), n in sorted(opened.items(), key=lambda kv: -kv[1]):
        print(f"  после {done:<18} СТАЛО валидным: {appeared:<20} (n={n})")
    for (done, gone), n in sorted(closed.items(), key=lambda kv: -kv[1]):
        print(f"  после {done:<18} перестало быть валидным: {gone:<14} (n={n})")
    print(f"  завершённых работ в выборке: {finished}")
    print()

    # ── 3. Достижимость после дороги ───────────────────────────────────────
    print("=" * 84)
    print("3. ДОРОГА И ДОСТИЖИМОСТЬ (сколько `goto_*` предложено до и после)")
    print("=" * 84)
    reach = [r for r in rows if r.get("kind") == "reach"]
    if not reach:
        print("  дорога в этих данных не завершалась — достижимость не измерена")
    for r in reach:
        print(f"  ход {r.get('turn')}: goto {r.get('goto_before')} → {r.get('goto_after')} "
              f"(клетка {r.get('x')},{r.get('y')})")
    print()
    print("Оговорка: каждая строка — наблюдение с конкретной клетки и юнита. "
          "Малое n (1–3) — это «есть факт», а не «есть закономерность».")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
