"""Что мир публикует об эффектах улучшений клеток и работы города."""
from __future__ import annotations

import json
import sys

w = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_ab116_A.json",
                  encoding="utf-8"))
eff = w.get("effects") or {}
for key in sorted(eff):
    if any(t in key for t in ("irrigation", "mine", "city_work", "city_unwork", "cultivate",
                              "plant", "road", "produce")):
        v = eff[key]
        print(f"{key}: seen={v.get('seen')}")
        print(f"    change_counts={v.get('change_counts')}")
        print(f"    horizon={v.get('horizon')}")