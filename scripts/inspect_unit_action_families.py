#!/usr/bin/env python3
"""List the action families a unit is offered in a real start state."""
from __future__ import annotations

import json
import os
import re
import sys

sys.argv = ["x"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    blob = json.load(open(os.path.join(ROOT, "tests", "fixtures",
                                       "real_obs_01.json"), encoding="utf-8"))
    snaps = blob if isinstance(blob, list) else [blob]
    for snap in snaps:
        info = snap.get("info") or {}
        obs = snap.get("observation") or {}
        if not (obs.get("unit") or {}):
            continue
        actions = (info.get("available_actions") or {}).get("unit") or {}
        names = set()
        for entry in actions.values():
            if isinstance(entry, dict):
                names |= set(entry)
            elif isinstance(entry, (list, tuple)):
                names |= {n for n in entry if isinstance(n, str)}
        families = sorted({re.sub(r"(_\d+)+$", "", n) for n in names})
        print(f"action names: {len(names)}, families: {len(families)}\n")
        for family in families:
            print(f"  {family}")
        return 0
    print("no snapshot with units")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())