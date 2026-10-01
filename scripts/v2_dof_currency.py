"""Валюты DoF: юниты считаются СЕМЕЙСТВАМИ, города — ПЕРЕХОДАМИ меню. Замер обеих сторон.

Нужно для честного сравнения «поселенец против города»: сейчас цены взяты из разных валют, и это
надо либо выровнять, либо явно признать.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world.json")
print("=== типы юнитов: обе меры ===")
rows = []
for t in sorted(g.by_kind("unit_type"), key=lambda x: -int(x.attrs.get("dof_mechanical") or 0)):
    mech = t.attrs.get("dof_mechanical")
    fam = t.attrs.get("dof_families")
    fams = t.attrs.get("families") or []
    if mech:
        rows.append((t.name, mech, fam, fams))
for name, mech, fam, fams in rows[:12]:
    print(f"  {name}: механических {mech}, семейств {fam} {fams}")
if rows:
    print(f"  медиана по {len(rows)} типам: механических "
          f"{statistics.median(r[1] for r in rows)}, семейств "
          f"{statistics.median(r[2] for r in rows if r[2])}")

print("\n=== города: переходы и семейства по размеру (из city_growth.jsonl) ===")
rows = [json.loads(l) for l in pathlib.Path("knowledge/city_growth.jsonl").read_text().splitlines() if l.strip()]
clean = [r for r in rows if isinstance(r.get("переходов_предложено"), int) and r["переходов_предложено"] > 0]
by: dict[int, list] = defaultdict(list)
fam: dict[int, list] = defaultdict(list)
for r in clean:
    by[r.get("размер")].append(r["переходов_предложено"])
    if isinstance(r.get("семейств"), int):
        fam[r.get("размер")].append(r["семейств"])
for size in sorted(k for k in by if isinstance(k, int)):
    print(f"  размер {size}: переходов медиана {statistics.median(by[size])} (n={len(by[size])})"
          f"; семейств медиана {statistics.median(fam[size]) if fam[size] else '—'}")

print("\n=== время роста города (пища) ===")
sf = [r.get("еда_прирост") for r in clean if isinstance(r.get("еда_прирост"), int)]
if sf:
    print(f"  еда_прирост: n={len(sf)} медиана {statistics.median(sf)} распределение "
          f"{dict(sorted(Counter(sf).items()))}")
    m = statistics.median(sf)
    if m > 0:
        print(f"  при foodbox=100: ходов на размер ≈ {100 / m:.0f} (медиана прироста {m})")
zs = [r.get("еда_прирост") for r in clean if isinstance(r.get("еда_прирост"), int) and r["еда_прирост"] <= 0]
print(f"  записей с нулевым/отрицательным приростом: {len(zs)}")