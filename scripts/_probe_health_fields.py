"""Что мир публикует про здоровье: свои юниты, чужие юниты, города."""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE = ROOT / "knowledge" / "live_trace_9570_port6003.jsonl"
TURNS = {94, 95, 96, 97}
PAT = re.compile(r"health|hp\b|hit|shield|щит|здоров|ранен", re.IGNORECASE)


def walk(node, path=""):
    if isinstance(node, dict):
        for key, val in node.items():
            yield from walk(val, f"{path}.{key}")
    elif isinstance(node, list):
        for i, val in enumerate(node[:400]):
            yield from walk(val, f"{path}[{i}]")
    else:
        yield path, node


def main() -> int:
    rows = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    print("верхние ключи записи:", sorted(rows[0].keys()))
    print()
    for row in rows:
        h = row.get("ход")
        if h not in TURNS:
            continue
        print(f"════ ход {h} ════")
        found = {}
        for path, val in walk(row):
            if PAT.search(path):
                leaf = path.rsplit(".", 1)[-1]
                found.setdefault(leaf, (path, val))
        for leaf, (path, val) in sorted(found.items())[:14]:
            print(f"   {leaf:20s} = {str(val)[:66]:66s} ({path[:50]})")
        if not found:
            print("   ничего похожего на здоровье не найдено")
        print("   упоминаний 'rank_':", len([1 for p, _ in walk(row) if "rank_" in p]),
              "| 'unit_' как значение:",
              len([1 for _, v in walk(row) if isinstance(v, str) and v.startswith("unit_")]))
    return 0


raise SystemExit(main())
