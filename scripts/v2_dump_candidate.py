"""Печатает сырой протокол кандидата города (для отладки разбора)."""

import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_prod.jsonl"
n = 0
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
    print("ход", r.get("ход"), "| ключи записи:", sorted(r.keys()))
    for c in r.get("кандидаты") or []:
        print("  кандидат:", json.dumps(c, ensure_ascii=False)[:700])
    n += 1
    if n >= 2:
        break