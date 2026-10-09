"""Записанный ряд индекса ядра по длинному прогону (§13.85; пересмотр §13.99).

ВАЖНО, названная граница инструмента: этот файл (`knowledge/live_trace_9570_port6003.jsonl`) хранит
РЕЗУЛЬТАТЫ замера (поля `ход`, `индекс`, `индекс_ядра`, `в_расчёте`, `вердикты`), а не сырые
наблюдения. Поэтому пересчитать индекс после правки порядка слоёв карты (§13.99) по нему НЕЛЬЗЯ:
нет входа. Здесь только читается то, что записано, и это честно называется.

Что известно про сдвиг: на фикстуре `real_obs_01` исправление порядка изменило индекс ядра с −0.8244
на −0.8293 (разница 0.0049 при |значении| 0.829 ⇒ ≈0.6 %). Для 150-ходового прогона перемер требует
сырого захвата — это отдельный долг, а не то, что можно подставить.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE = ROOT / "knowledge" / "live_trace_9570_port6003.jsonl"


def main() -> int:
    if not TRACE.exists():
        print("трассы нет:", TRACE)
        return 2
    rows: list[dict] = []
    for line in TRACE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    print(f"записей: {len(rows)}")
    if not rows:
        return 2
    idx = [(r.get("ход"), r.get("индекс_ядра"), r.get("в_расчёте")) for r in rows]
    for turn, value, count in idx[:2] + idx[len(idx) // 2:len(idx) // 2 + 1] + idx[-2:]:
        print(f"  ход {turn}: индекс ядра {value}; в наборе {count}")
    vals = [v for _, v, _ in idx if isinstance(v, (int, float))]
    if vals:
        print(f"  минимум {min(vals):.4f}, максимум {max(vals):.4f}")
    print("\n§13.85 опубликовал: ход 1 — −3.8212, ход 150 — −18.7897 (считано до правки §13.99).")
    return 0


raise SystemExit(main())
