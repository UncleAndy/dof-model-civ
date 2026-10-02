"""Разбор трассы: меняет ли город производство каждый ход (flip-flop) и видно ли цену отказа.

Запуск: .venv/bin/python scripts/v2_produce_sequence.py knowledge/traces_switch2.jsonl
"""
from __future__ import annotations

import collections
import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_switch2.jsonl"
    seq: dict[str, list] = collections.defaultdict(list)
    pen_rows = 0
    pen_examples: list[str] = []
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        ch = r.get("выбрано")
        if ch and ch.get("steps"):
            s = ch["steps"][0]
            if str(s.get("action", "")).startswith("produce_"):
                seq[str(s["actor"])].append((r.get("ход"), s["action"][len("produce_"):]))
        for c in r.get("кандидаты") or []:
            why = str(c.get("почему") or "")
            if "отказ от" in why:
                pen_rows += 1
                if len(pen_examples) < 2:
                    pen_examples.append(why[:220])
    print(f"решений с ценой отказа в протоколе: {pen_rows}")
    for ex in pen_examples:
        print("  пример:", ex)
    for actor, v in sorted(seq.items()):
        print(f"\nгород {actor}: установок производства {len(v)}")
        print("  ", v[:20])
        switches = sum(1 for i in range(1, len(v)) if v[i][1] != v[i - 1][1])
        print(f"  смен варианта: {switches} из {max(0, len(v) - 1)} переходов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())