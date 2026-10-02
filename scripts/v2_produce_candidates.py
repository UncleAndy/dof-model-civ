"""Показать, что модель считает по вариантам производства города (net_delta и причина).

Запуск: .venv/bin/python scripts/v2_produce_candidates.py knowledge/traces_switch2.jsonl [сколько_ходов]
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_switch2.jsonl"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    shown = 0
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        cands = [c for c in (r.get("кандидаты") or [])
                 if isinstance(c.get("эффект"), list) and c["эффект"][:2] == ["channel", "city"]]
        if not cands:
            continue
        print(f"\n=== ход {r.get('ход')} ===")
        for c in cands:
            print(f"  net {c.get('net_delta')}")
            print(f"     {str(c.get('почему'))[:600]}")
        shown += 1
        if shown >= limit:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())