"""Публикует ли мир имена местностей и дополнений (terrain/extra)?

От этого зависит, можно ли назвать океан и реку ПО ДАННЫМ, а не по памяти о правилах. Проверяются
секции, которые могут нести справочники: `rules`, `options`, `game`, `gov`, `client`.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    obs = rows[-1]["observation"]
    for key in ("rules", "options", "game", "gov", "client", "player"):
        v = obs.get(key)
        if isinstance(v, dict):
            keys = sorted(v)
            print(f"\n{key}: {len(keys)} ключей; первые: {keys[:14]}")
            for k in keys[:40]:
                val = v[k]
                if isinstance(val, (list, dict)) and len(val) > 3:
                    print(f"   {k}: {type(val).__name__} длины {len(val)} — {str(val)[:180]}")
        elif isinstance(v, list):
            print(f"\n{key}: список длины {len(v)} — {str(v[:6])[:220]}")
        else:
            print(f"\n{key}: {type(v).__name__}")
    # Ищем любые упоминания местностей/дополнений в тексте среза
    blob = json.dumps(obs, ensure_ascii=False).lower()
    for probe in ("terrain", "ocean", "river", "grassland", "extra", "hill", "forest"):
        print(f"упоминаний {probe!r} в срезе: {blob.count(probe)}")
    return 0


raise SystemExit(main())
