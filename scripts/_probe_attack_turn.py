"""§13.85: подробности хода нападения (96) — канал коллапса и состояние раненого юнита."""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE = ROOT / "knowledge" / "live_trace_9570_port6003.jsonl"
LO, HI = 92, 102
UNIT = "unit_111"


def main() -> int:
    rows = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    sample = next(iter((rows[0].get("вердикты") or {}).values()), {}) or {}
    print("ключи строки вердикта в записи:", sorted(sample.keys()))
    for row in rows:
        h = row.get("ход")
        if not isinstance(h, int) or not (LO <= h <= HI):
            continue
        channel = row.get("кандидаты_коллапса") or {}
        verdicts = row.get("вердикты") or {}
        ids = {str(x.get("id")) for x in (row.get("разбивка") or []) if isinstance(x, dict)}
        v = verdicts.get(UNIT) or {}
        print(f"ход {h}: потерь {len(channel.get('losses') or [])}, посторонних "
              f"{len(channel.get('extraneous') or [])}, кандидатов "
              f"{len(channel.get('candidates') or [])}, причина: "
              f"{str(channel.get('reason'))[:74]}")
        print(f"    {UNIT}: {'в наборе' if UNIT in ids else 'вне набора'}, "
              f"вердикт {v.get('вердикт')}, причина {str(v.get('причина'))[:70]}, "
              f"в наборе всего {row.get('в_расчёте')}, индекс {row.get('индекс')}")
        for key in ("losses", "extraneous", "candidates"):
            items = channel.get(key) or []
            if items:
                print(f"    {key}: {json.dumps(items, ensure_ascii=False)[:250]}")
    return 0


raise SystemExit(main())
