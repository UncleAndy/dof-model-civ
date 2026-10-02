"""Показать простаивающий ход: какие кандидаты были и почему ни один не выбран.

Запуск: .venv/bin/python scripts/v2_show_idle_turn.py knowledge/traces_nocut.jsonl
"""
from __future__ import annotations

import collections
import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_nocut.jsonl"
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
    per = collections.Counter(r.get("ход") for r in rows)
    idle = sorted(t for t, n in per.items() if isinstance(t, int) and n <= 2)
    print("простаивающих ходов:", idle[:20])
    target = idle[0] if idle else None
    for r in rows:
        if r.get("ход") != target:
            continue
        print(f"\n=== ход {target}: путей {r.get('путей')}, целей без пути {r.get('целей_без_пути')}, "
              f"причина: {r.get('причина')}")
        for c in r.get("кандидаты") or []:
            print(f"  {c.get('эффект')} net={c.get('net_delta')}")
            print(f"     {str(c.get('почему'))[:300]}")
        print("  чужое:", r.get("чужое"))
        print("  источники коллапса:", r.get("источники_коллапса"))
        print("  кальк_исключено:", str(r.get("кальк_исключено"))[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())