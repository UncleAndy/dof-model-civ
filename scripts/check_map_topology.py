#!/usr/bin/env python
"""Какая у карты топология — по самому наблюдению, а не по памяти.

От этого зависит критика `tile_output`: если по Y карта НЕ замыкается, то замыкание
обеих осей подставляет площадке у полюса соседей с другого края.

    python scripts/check_map_topology.py
"""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ("topology", "topology_id", "xsize", "ysize", "wrap")


def main() -> int:
    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]
    for section in ("map", "game", "rules", "client"):
        data = obs.get(section) or {}
        if not isinstance(data, dict):
            continue
        found = {k: data[k] for k in data if any(part in k.lower() for part in KEYS)}
        print(f"{section}: {found if found else '— ничего про топологию/размеры'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
