"""Что мир отдаёт про постройки города и есть ли таблица имён типов юнитов.

Нужно для В1: DoF города = своё меню + достижимое (то, что он может построить). Чтобы это считалось
замером, нужны: (1) список разрешённых построек, (2) имена/типы этих построек, (3) сроки постройки.
"""
from __future__ import annotations

import glob
import json
import pathlib
import sys

CANDIDATES = ["tests/fixtures/real_obs_01.json", "/tmp/v2_capture_seed9000.json",
              *sorted(glob.glob("knowledge/*.json"))]
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
    cities = obs.get("city") or {}
    if not cities:
        continue
    print(f"=== {path} ===")
    cid, c = next(iter(cities.items()))
    print("поля города:", sorted(c.keys()))
    for k in ("can_build_unit", "can_build_improvement", "n_buildable", "production_kind",
              "production_value", "buildable_here", "prod_kind"):
        if k in c:
            v = c[k]
            if isinstance(v, list) and len(v) > 40:
                allowed = [i for i, x in enumerate(v) if x]
                print(f"  {k}: длина {len(v)}, разрешено {len(allowed)} → индексы {allowed[:15]}")
            else:
                print(f"  {k}: {str(v)[:200]}")
    # таблица имён типов
    for key in ("unit_type", "rules", "player"):
        sec = obs.get(key)
        if isinstance(sec, dict):
            print(f"  секция {key}: ключей {len(sec)}; пример ключей {list(sec)[:5]}")
            if sec:
                k0 = next(iter(sec))
                print(f"    пример {key}[{k0}]: {str(sec[k0])[:220]}")
    break
else:
    print("наблюдений с городом не найдено")