"""Полные записи требований видов 3/14/22: какие поля мир публикует и что они значат.

Без `range` требование вида «нужна постройка» и «нужна река» не оценить: одно про сам город, другое
про его окрестность. Здесь печатаются ВСЕ поля без отбора, чтобы решение опиралось на данные.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    obs = rows[-1]["observation"]
    tech = obs.get("tech") or {}

    fields: collections.Counter = collections.Counter()
    by_kind: dict[object, list] = collections.defaultdict(list)
    for tid, rec in tech.items():
        if not isinstance(rec, dict):
            continue
        for key, req_key in (("sup_units", "build_reqs"), ("sup_improvements", "reqs")):
            for spec in (rec.get(key) or []):
                if not isinstance(spec, dict):
                    continue
                for req in (spec.get(req_key) or []):
                    if not isinstance(req, dict):
                        continue
                    for f in req:
                        fields[f] += 1
                    if req.get("kind") in (3, 14, 22):
                        by_kind[req.get("kind")].append((str(spec.get("name")), dict(req), req_key))

    print("поля, которые публикует мир в требовании:", dict(fields))
    for kind in sorted(by_kind):
        rows_k = by_kind[kind]
        print(f"\nkind={kind}: {len(rows_k)}")
        seen = set()
        for name, req, req_key in rows_k:
            key2 = (req.get("kind"), req.get("value"), req.get("range"), req.get("present"),
                    req.get("survives"))
            if key2 in seen:
                continue
            seen.add(key2)
            print(f"   · {name:22s} {req}   ({req_key})")

    # Что мир публикует о НАШЕМ городе: маска улучшений и клетка (для приморья и реки).
    city = next(((k, v) for k, v in (obs.get("city") or {}).items()
                 if isinstance(v, dict) and int(v.get("owner", 0) or 0) == 0), None)
    if city:
        cid, rec = city
        print(f"\nнаш город {cid}: поля {sorted(rec)[:24]}")
        print("  x,y:", rec.get("x"), rec.get("y"), "| improvements:", rec.get("improvements"))
    mp = obs.get("map") or {}
    print("\nсекция map: ключи", sorted(mp)[:12])
    for k in ("river", "terrain", "t0000", "unit_owner"):
        v = mp.get(k)
        shape = (len(v), type(v[0]).__name__) if isinstance(v, list) and v else type(v).__name__
        print(f"  {k}: {shape}")
    return 0


raise SystemExit(main())
