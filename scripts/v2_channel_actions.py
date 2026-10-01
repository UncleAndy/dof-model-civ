"""Какие ДЕЙСТВИЯ реально стояли в ветке `channel` (там живут действия города).

Нужно, чтобы увидеть состав меню города именами, а не только числом переходов.
"""
from __future__ import annotations

import collections
import glob
import json
import pathlib
import sys

paths = sys.argv[1:] or sorted(glob.glob("knowledge/traces_*.jsonl"))
chosen_actions: collections.Counter = collections.Counter()
cand_actions: collections.Counter = collections.Counter()
ctrl_of_action: dict[str, str] = {}
for path in paths:
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for st in ((rec.get("выбрано") or {}).get("steps") or []):
            if (rec.get("выбрано") or {}).get("goal") == "channel":
                chosen_actions[st.get("action")] += 1
                ctrl_of_action[st.get("action")] = st.get("ctrl")
        for c in rec.get("кандидаты") or []:
            eff = c.get("эффект") or []
            if eff and eff[0] == "channel":
                cand_actions[str(eff[1]) if len(eff) > 1 else "?"] += 1

print("действия, ВЫБРАННЫЕ в ветке channel (топ-25):")
for a, n in chosen_actions.most_common(25):
    print(f"  {a} [{ctrl_of_action.get(a)}]: {n}")
print(f"\nвсего разных действий в channel-кандидатах: {len(cand_actions)}; топ-25:")
for a, n in cand_actions.most_common(25):
    print(f"  {a}: {n}")