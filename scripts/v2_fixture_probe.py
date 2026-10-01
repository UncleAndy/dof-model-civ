"""Разбор структуры фикстуры наблюдения: где город и какие у него поля."""
from __future__ import annotations

import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/real_obs_01.json"
d = json.loads(open(path).read())
print("верхние ключи:", list(d)[:15] if isinstance(d, dict) else type(d).__name__)
obs = (d.get("observation") or d) if isinstance(d, dict) else d
print("ключи наблюдения:", list(obs)[:20])
for key in ("city", "unit", "player", "map", "rules", "unit_type", "improvement"):
    sec = obs.get(key)
    if sec is None:
        continue
    if isinstance(sec, dict):
        print(f"\n{key}: {len(sec)} записей; ключи {list(sec)[:5]}")
        if sec:
            k0 = next(iter(sec))
            body = sec[k0]
            if isinstance(body, dict):
                print(f"  {key}[{k0}] поля: {sorted(body.keys())}")
                print(f"  {key}[{k0}]: {json.dumps(body, ensure_ascii=False)[:600]}")
            else:
                print(f"  {key}[{k0}]: {str(body)[:200]}")
    else:
        print(f"\n{key}: {type(sec).__name__} {str(sec)[:200]}")