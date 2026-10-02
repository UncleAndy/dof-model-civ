"""Разбор выбора производства: что предложено, с какой ценой и что выбрано (по ходам).

Запуск: .venv/bin/python scripts/v2_produce_variants.py knowledge/traces_prod.jsonl [сколько_ходов]
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_prod.jsonl"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    shown = 0
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        ch = r.get("выбрано")
        if not (ch and ch.get("steps") and str(ch["steps"][0].get("action", "")).startswith("produce_")):
            continue
        cands = [c for c in (r.get("кандидаты") or [])
                 if isinstance(c.get("эффект"), list) and c["эффект"][:2] == ["channel", "city"]]
        print(f"\n=== ход {r.get('ход')}: выбрано {ch['steps'][0]['action']} "
              f"(актор {ch['steps'][0]['actor']}) ===")
        for c in cands:
            for v in (c.get("варианты") or []):
                print(f"   {str(v.get('действие')):22} net={v.get('net_delta')} "
                      f"{'срок неизвестен' if v.get('срок_неизвестен') else ''}")
        shown += 1
        if shown >= limit:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())