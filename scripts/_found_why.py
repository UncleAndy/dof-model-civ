"""Замер B: из чего складывается цена found_city.

Печатает: проекцию build_city (что появляется/исчезает), impute города и юнита,
базовую часть цены и её сверку с наблюдаемым net_delta.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402
from brain.v2.calculus import impute  # noqa: E402
from brain.v2 import projection as proj_mod  # noqa: E402
import math  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_def7.json")
p = proj_mod.project(g, "unit", "build_city")
print("проекция unit/build_city: known=", p.known, " source=", p.source)
print("  new_entities =", p.new_entities)
print("  lost_entities =", p.lost_entities)
print("  changes =", p.changes)

ic, nc = impute(g, "city")
iu, nu = impute(g, "unit")
print(f"\nimpute(city) = {ic} (записей {nc})   → ln = {math.log(ic):.3f}" if ic else f"impute(city) = {ic}")
print(f"impute(unit) = {iu} (записей {nu})   → ln = {math.log(iu):.3f}" if iu else f"impute(unit) = {iu}")

base = 0.0
for kind, n in (p.new_entities or {}).items():
    v, _ = impute(g, kind)
    if v:
        base += n * math.log(v)
        print(f"  + {n}×ln({v:g}) [{kind}] = +{n*math.log(v):.3f}")
for kind, n in (p.lost_entities or {}).items():
    v, _ = impute(g, kind)
    if v:
        base -= n * math.log(v)
        print(f"  − {n}×ln({v:g}) [{kind}] = −{n*math.log(v):.3f}")
print(f"\nБАЗА цены found_city = {base:.3f}")

# сверка с наблюдаемыми net_delta из трейса
for path in ("knowledge/traces_def7.jsonl",):
    lines = open(path, encoding="utf-8").read().splitlines()
    vals = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except Exception:
            continue
        for c in (d.get("кандидаты") or []):
            eff = c.get("эффект")
            if isinstance(eff, list) and eff and eff[0] == "found_city":
                if c.get("net_delta") is not None:
                    vals.append(c["net_delta"])
    if vals:
        vals.sort()
        import statistics
        print(f"\nнаблюдаемых net_delta found_city: {len(vals)}; "
              f"мин {vals[0]:.3f}, медиана {statistics.median(vals):.3f}, макс {vals[-1]:.3f}")
