"""Долг «23 требования не-технологических видов»: ЧТО это за виды и сколько их.

Считается по настоящему захвату (`tests/fixtures/real_obs_01.json`), а не по памяти о правилах
Freeciv. Печатается: распределение требований по `kind`, примеры записей и контрольная сверка с
счётчиком каталога `unevaluated` (должен сойтись — иначе я читаю не то место).
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
    tech = rows[-1]["observation"].get("tech") or {}
    print(f"технологий в срезе: {len(tech)}; записей с предметами: "
          f"{sum(1 for r in tech.values() if isinstance(r, dict) and (r.get('sup_units') or r.get('sup_improvements')))}")

    by_kind: collections.Counter = collections.Counter()
    samples: dict[object, list] = {}
    present_by_kind: collections.Counter = collections.Counter()
    items_other = collections.Counter()
    for tid, rec in tech.items():
        if not isinstance(rec, dict):
            continue
        for key, req_key in (("sup_units", "build_reqs"), ("sup_improvements", "reqs")):
            for spec in (rec.get(key) or []):
                if not isinstance(spec, dict):
                    continue
                name = str(spec.get("name") or "?")
                others = 0
                for req in (spec.get(req_key) or []):
                    if not isinstance(req, dict):
                        continue
                    kind = req.get("kind")
                    by_kind[kind] += 1
                    if req.get("present"):
                        present_by_kind[kind] += 1
                    if kind != 1 and req.get("present"):
                        others += 1
                    samples.setdefault(kind, [])
                    if len(samples[kind]) < 3:
                        samples[kind].append((name, req.get("value"), bool(req.get("present")),
                                              req_key))
                if others:
                    items_other[name] = max(items_other[name], others)

    print("\nвид требования -> всего записей / из них present:")
    for kind, cnt in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  kind={kind!r}: {cnt} / {present_by_kind[kind]}")
        for name, value, present, req_key in samples[kind]:
            print(f"      · {name}: value={value!r} present={present} ({req_key})")
    print("\nпредметов с не-технологическими требованиями:", len(items_other))
    print("сумма неоценённых по каталогу:", sum(items_other.values()))

    cat = L.catalogue_index(tech)
    print("каталог мира: предметов", len(cat["items"]), "| unevaluated", cat["unevaluated"],
          "| технологий-открывателей", len(cat["unlocks"]))
    print("сходится со счётом моим:", sum(items_other.values()) == cat["unevaluated"])
    return 0


raise SystemExit(main())
