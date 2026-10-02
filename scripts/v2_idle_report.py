"""Разбор трассы по партиям: сколько решений на ход и почему ход закрывается.

Запуск: .venv/bin/python scripts/v2_idle_report.py knowledge/traces_keep_video.jsonl
"""
from __future__ import annotations

import collections
import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_keep_video.jsonl"
    rows = []
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if "решение" in r:
            rows.append(r)
    # делим на партии по сбросу номера хода
    games: list[list[dict]] = []
    cur: list[dict] = []
    last = None
    for r in rows:
        t = r.get("ход")
        if isinstance(t, int) and isinstance(last, int) and t < last:
            games.append(cur)
            cur = []
        cur.append(r)
        last = t
    if cur:
        games.append(cur)
    for gi, g in enumerate(games, 1):
        per = collections.Counter(r.get("ход") for r in g)
        reasons = collections.Counter()
        fams = collections.Counter()
        nochoice = 0
        for r in g:
            ch = r.get("выбрано")
            if ch and ch.get("steps"):
                fams[str(ch["steps"][0]["action"]).split("_")[0]] += 1
            else:
                nochoice += 1
                reasons[str(r.get("причина"))[:70]] += 1
        print(f"\n=== партия {gi}: ходов {len(per)}, решений {len(g)}, "
              f"решений/ход {sorted(set(per.values()))}")
        print(f"    семейства: {fams.most_common(6)}")
        print(f"    без выбора: {nochoice}; причины: {reasons.most_common(3)}")
        idle_turns = sum(1 for t, n in per.items() if n <= 2)
        print(f"    ходов с ≤2 решениями: {idle_turns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())