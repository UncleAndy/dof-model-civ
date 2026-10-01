"""Что реально лежит в меню города и в списке постройки — по живым наблюдениям.

Нужно, чтобы предложить варианты с числами: сколько действий у города СЕЙЧАС, сколько позиций он
может построить, и какие DoF у того, что он может построить.
"""
from __future__ import annotations

import glob
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

CANDIDATES = [
    "tests/fixtures/real_obs_01.json",
    "/tmp/v2_capture_seed9000.json",
    *sorted(glob.glob("knowledge/*.json")),
]
seen_menu = 0
for path in CANDIDATES:
    p = pathlib.Path(path)
    if not p.exists():
        continue
    try:
        data = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        continue
    if not isinstance(data, dict):
        continue
    obs = data.get("observation") or data
    avail = data.get("available_actions") or {}
    cities = obs.get("city") or {}
    menu = (avail or {}).get("city") or {}
    if not cities:
        continue
    print(f"\n=== {path}: городов {len(cities)}, секция меню city: {len(menu)} ===")
    for cid, c in list(cities.items())[:1]:
        print(f"  город {cid}: имя={c.get('name')}, размер={c.get('size')}, "
              f"n_buildable={c.get('n_buildable')}")
        cbu = c.get("can_build_unit")
        if cbu:
            allowed = [i for i, v in enumerate(cbu) if v] if isinstance(cbu, list) else None
            print(f"  can_build_unit: длина {len(cbu)}, разрешено {len(allowed) if allowed else '—'} "
                  f"(индексы {allowed[:12] if allowed else '—'})")
        for k in ("can_build_improvement", "can_build_unit_here", "production_kind", "prod_kind"):
            if k in c:
                print(f"  {k}: {str(c[k])[:120]}")
    for cid, opts in list(menu.items())[:1]:
        names = sorted(a for a, ok in (opts or {}).items() if ok)
        print(f"  меню города {cid}: {len(names)} действий → {names[:20]}")
        seen_menu += 1

print(f"\nнаблюдений с меню города: {seen_menu}")
# какие имена вообще встречаются в меню по всем файлам трасс
names: Counter = Counter()
for pat in ("knowledge/traces_*.jsonl",):
    for f in glob.glob(pat):
        for line in pathlib.Path(f).read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            for c in rec.get("кандидаты") or []:
                eff = c.get("эффект") or []
                if eff:
                    names[eff[0]] += 1
print("семейства, встречавшиеся в кандидатах:", dict(names.most_common(12)))