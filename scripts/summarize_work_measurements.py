#!/usr/bin/env python
"""Свод замеров работ по логам прогонов: готовые строки для таблицы эффектов.

Читает логи `measure_terrain_effect.py` (файлы вида /tmp/tw_*.log), вытаскивает
строки изменений и печатает:
  * для каждой пары (работа, террейн) — набор наблюдённых Δ(еда, щиты, торговля);
  * отдельно — строки, где изменился САМ террейн (то есть это transform, а не
    экстра) и строки, где изменился только слой экстр (экстра поставлена, но
    выхода не добавила — это тоже результат, а не «не измерено»).

Использование:
    python scripts/summarize_work_measurements.py /tmp/tw_4.log /tmp/tw_7.log ...
"""
import re
import sys
from collections import defaultdict

LINE = re.compile(
    r"turn (?P<turn>\d+): ИЗМЕНЕНИЕ (?P<tname>\S+) @\((?P<x>\d+),(?P<y>\d+)\) "
    r"(?P<work>[\w_]+): \((?P<b0>-?\d+), (?P<b1>-?\d+), (?P<b2>-?\d+)\) -> "
    r"\((?P<n0>-?\d+), (?P<n1>-?\d+), (?P<n2>-?\d+)\) \(Δ=\((?P<d0>-?\d+), "
    r"(?P<d1>-?\d+), (?P<d2>-?\d+)\)\); террейн (?P<t_before>\S+) -> (?P<t_after>\S+); "
    r"экстры \[(?P<e_before>[^\]]*)\] -> \[(?P<e_after>[^\]]*)\]")


def main(paths: list[str]) -> int:
    effects = defaultdict(set)
    transforms = defaultdict(set)
    extra_only = defaultdict(set)
    for path in paths:
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            print(f"  {path}: {exc}")
            continue
        for m in LINE.finditer(text):
            work = m["work"]
            terrain = m["t_before"]
            delta = (int(m["d0"]), int(m["d1"]), int(m["d2"]))
            terrain_changed = m["t_before"] != m["t_after"]
            extras_changed = m["e_before"].strip() != m["e_after"].strip()
            if terrain_changed:
                transforms[(work, terrain)].add(f"{terrain} -> {m['t_after']}")
            elif extras_changed and delta == (0, 0, 0):
                extra_only[(work, terrain)].add(m["e_after"].strip())
            effects[(work, terrain)].add(delta)

    print("=== ИЗМЕНЕНИЕ ВЫХОДА (работа, террейн) -> Δ ===")
    if not effects:
        print("  нет наблюдений")
    for (work, terrain), deltas in sorted(effects.items()):
        print(f"  {work} на {terrain}: {sorted(deltas)}")

    print("\n=== ЭКСТРА ПОСТАВЛЕНА, ВЫХОД НЕ ИЗМЕНИЛСЯ (тоже результат) ===")
    for (work, terrain), after in sorted(extra_only.items()):
        print(f"  {work} на {terrain}: экстры стали {sorted(after)}")

    print("\n=== СМЕНА ТЕРРЕЙНА (не экстра, цена зависит от результата) ===")
    for (work, terrain), results in sorted(transforms.items()):
        print(f"  {work} на {terrain}: {sorted(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
