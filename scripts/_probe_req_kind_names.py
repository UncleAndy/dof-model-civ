"""Опознание видов требований: чем является `value` каждого вида в ДАННЫХ мира.

Для каждого встреченного `kind` значение разрешается по справочникам, которые публикует мир
(улучшения, типы юнитов, местность, ресурсы). Вид считается опознанным, если ВСЕ его значения
попадают в один справочник и имена согласуются со смыслом предмета.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import spec_lenses as L   # noqa: E402


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    obs = rows[-1]["observation"]
    tech = obs.get("tech") or {}

    imp = L.improvement_id_index(tech)
    units = L.unit_order_index()
    print("справочники мира: улучшений", len(imp), "| типов юнитов", len(units))
    print("улучшения (id -> имя):", dict(sorted(imp.items())[:12]))

    seen: dict[object, list] = collections.defaultdict(list)
    for tid, rec in tech.items():
        if not isinstance(rec, dict):
            continue
        for key, req_key in (("sup_units", "build_reqs"), ("sup_improvements", "reqs")):
            for spec in (rec.get(key) or []):
                if not isinstance(spec, dict):
                    continue
                for req in (spec.get(req_key) or []):
                    if isinstance(req, dict) and req.get("present") and req.get("kind") != 1:
                        seen[req.get("kind")].append((str(spec.get("name")), req.get("value")))

    for kind, rows_k in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        as_imp = [imp.get(int(v)) if str(v).lstrip("-").isdigit() else None for _, v in rows_k]
        as_unit = [units.get(int(v)) if str(v).lstrip("-").isdigit() else None for _, v in rows_k]
        print(f"\nkind={kind!r}: {len(rows_k)} записей")
        for (name, value), i_name, u_name in list(zip(rows_k, as_imp, as_unit))[:8]:
            print(f"   · {name:22s} value={value!r:6} -> улучшение {i_name!r}, юнит {u_name!r}")
        print(f"   попаданий в улучшения: {sum(1 for x in as_imp if x)}, в юниты: "
              f"{sum(1 for x in as_unit if x)}")
    return 0


raise SystemExit(main())
