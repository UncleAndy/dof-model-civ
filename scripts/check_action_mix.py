#!/usr/bin/env python
"""Что за действия агент реально отправлял: состав по контроллерам.

Нужно, чтобы отличить «прогноз действует» от «прогноз трогает только один канал».
Печатает состав из записи прогона, ничего не додумывая: если поля с составом нет,
так и говорит.

    python scripts/check_action_mix.py forecast_smoke14.json
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "forecast_smoke14.json"
    with open(os.path.join(HERE, path), encoding="utf-8") as handle:
        doc = json.load(handle)

    results = doc.get("results")
    print(f"тип results: {type(results).__name__}")
    for index, entry in enumerate(results if isinstance(results, list) else [results]):
        print(f"\n=== запись {index}: {type(entry).__name__}")
        if not isinstance(entry, dict):
            print(f"   {entry!r}")
            continue
        for name, row in entry.items():
            if not isinstance(row, dict):
                print(f"   {name}: {row!r}")
                continue
            print(f"   {name}: ключи {sorted(row.keys())}")
            for key, value in row.items():
                if "action" in key or "mix" in key or "famil" in key:
                    print(f"      {key} = "
                          f"{json.dumps(value, ensure_ascii=False, default=str)[:400]}")
            for key in ("decisions", "decision_actions", "actions"):
                if key in row and isinstance(row[key], list):
                    counts = Counter()
                    for item in row[key]:
                        if isinstance(item, dict):
                            counts[(item.get("ctrl_type"),
                                    str(item.get("action_name", "")).split("_")[0])] += 1
                        elif isinstance(item, (list, tuple)) and len(item) >= 3:
                            counts[(item[0], str(item[2]).split("_")[0])] += 1
                    print(f"      {key}: {dict(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
