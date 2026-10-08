"""Проба §13.82: вердикты достижимости по сущностям и смена вердикта от хода к ходу.

Разводит два случая выпадения из набора: по вердикту proven_unreachable и без него.
"""
from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
KN = ROOT / "knowledge"

path = sorted(KN.glob("live_trace_9560_port6003.jsonl"))[0]
rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
print(f"запись: {path.name}, ходов: {len(rows)}")
if not rows or not rows[0].get("вердикты"):
    print("вердиктов в записи нет — судить нечего")
    raise SystemExit(0)

print("\n── распределение вердиктов по ходам ──")
for r in rows:
    v = r.get("вердикты") or {}
    c = collections.Counter((x or {}).get("вердикт") for x in v.values())
    print(f'  ход {r.get("ход"):>3}: всего {len(v):>3} | ' +
          " | ".join(f"{k}={n}" for k, n in sorted(c.items(), key=lambda kv: str(kv[0]))))

per_entity: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
for r in rows:
    for eid, rec in (r.get("вердикты") or {}).items():
        per_entity[eid].append((r.get("ход"), (rec or {}).get("вердикт")))

changed = {e: seq for e, seq in per_entity.items()
           if len({v for _, v in seq}) > 1}
print(f"\n── сущностей всего: {len(per_entity)}; сменивших вердикт: {len(changed)} ──")
for e, seq in list(changed.items())[:10]:
    print(f"  {e}: " + " → ".join(f"{v}" for _, v in seq))

back = {e: seq for e, seq in per_entity.items()
        if any(v == "proven_unreachable" for _, v in seq)
        and any(v == "reachable" for h, v in seq
                if h > min(h2 for h2, v2 in seq if v2 == "proven_unreachable"))}
print(f"\n  переход proven_unreachable → reachable: {len(back)}")
if back:
    print("  вердикт по объявленному правилу: односторонность ОПРОВЕРГНУТА")
else:
    print("  вердикт по объявленному правилу: обратного перехода не наблюдалось")

print("\n── выпадения из набора и вердикты ──")
sets = [{x.get("id") for x in (r.get("разбивка") or []) if x.get("id")} for r in rows]
with_v, without_v = set(), set()
for i in range(1, len(rows)):
    gone = sets[i - 1] - sets[i]
    for name in gone:
        v = ((rows[i].get("вердикты") or {}).get(name) or {}).get("вердикт")
        (with_v if v == "proven_unreachable" else without_v).add((name, str(v)))
print(f"  выпало по вердикту proven_unreachable: {len(with_v)}")
print(f"  выпало при другом вердикте (или без него): {len(without_v)}")
if without_v:
    print(f"  примеры: {sorted(without_v)[:6]}")
