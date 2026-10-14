"""Сравнение сторон в одной партии: читает `[состав сторон]` из лога и печатает таблицу.

Замер §13.333: мир публикует состав по КАЖДОЙ стороне, поэтому встроенный ИИ мерится
в той же партии и на той же карте, что и мы. Это снимает разброс случайной карты,
из-за которого отдельные плечи не различали разницу (§13.330).

Запуск:  python scripts/_sides_table.py /tmp/dof_ref4.log [ещё логи...]
"""
from __future__ import annotations

import re
import statistics as st
import sys
from pathlib import Path

LINE = re.compile(r"\[состав сторон\]\s+(?P<name>.+?)\s+\(id (?P<id>\d+)\):\s+(?P<vals>.+)$")


def parse(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.search(line)
        if not m:
            continue
        vals = {k: float(v) for k, v in re.findall(r"(\w+)=(-?\d+)", m.group("vals"))}
        rows.append({"log": path.name, "name": m.group("name"), "id": int(m.group("id")), **vals})
    return rows


def main(paths: list[str]) -> None:
    rows = []
    for p in paths:
        rows.extend(parse(Path(p)))
    if not rows:
        print("строк «[состав сторон]» не найдено")
        return

    # наши строки — те, где сторона одна и совпадает по имени с логином (id 0 в замерах)
    keys = ["score", "cities", "population", "researched_techs", "land_area",
            "settled_area", "gold", "units_built", "military_units", "production"]
    ours = [r for r in rows if r["id"] == 0]
    theirs = [r for r in rows if r["id"] != 0]

    print(f"партий с замером: {len(ours)}; сторон-ИИ: {len(theirs)}")
    print()
    hdr = f"{'статья':<18}{'мы (среднее)':>14}{'ИИ (среднее)':>14}{'ИИ (разброс)':>16}"
    print(hdr)
    print("-" * len(hdr))
    for k in keys:
        a = [r[k] for r in ours if k in r]
        b = [r[k] for r in theirs if k in r]
        if not a or not b:
            continue
        spread = f"{min(b):.0f}..{max(b):.0f}" if b else "—"
        ratio = (st.mean(b) / st.mean(a)) if st.mean(a) else float("inf")
        print(f"{k:<18}{st.mean(a):>14.1f}{st.mean(b):>14.1f}{spread:>16}   ×{ratio:.1f}")
    print()
    for r in ours:
        print(f"  наша партия {r['log']}: score={r.get('score')} cities={r.get('cities')} "
              f"population={r.get('population')} techs={r.get('researched_techs')}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["/tmp/dof_ref4.log"])
