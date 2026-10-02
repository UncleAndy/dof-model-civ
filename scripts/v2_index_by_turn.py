"""Диагностика простоя: сколько сущностей в индексе и сколько путей по ходам.

Запуск: .venv/bin/python scripts/v2_index_by_turn.py knowledge/traces_nocut.jsonl
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_nocut.jsonl"
    seen: set = set()
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if "решение" not in r:
            continue
        t = r.get("ход")
        if t in seen:
            continue
        seen.add(t)
        print(f"ход {t:>3}: индекс_сущностей {r.get('кальк_включено')}, путей {r.get('путей')}, "
              f"целей_без_пути {r.get('целей_без_пути')}, "
              f"чужое_юнитов {(r.get('чужое') or {}).get('юнитов')}, "
              f"источники_коллапса {len(r.get('источники_коллапса') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())