#!/usr/bin/env python
"""Сводка замера дороги: цена шага по парам «местность→местность» и с дорогой/без.

Правило вердикта задано ДО данных (см. `scripts/measure_road_value.py`):

  H1 — шаг на клетку с дорогой стоит меньше, чем на ту же местность без дороги;
  H0 — не стоит меньше (дорога движению не помогает — измеренный ноль).

Дополнительно печатается всё, что нужно, чтобы не спутать «нет эффекта» с «не было
дорог»: сколько строк с дорогой вообще есть, и какая цена шага по местностям.

Важно про единицы: freeciv хранит очки движения в ТРЕТЯХ (MOVE_FRACTION = 3),
поэтому `moves` = 3 у юнита с ходом 1. Цена шага 3 = целое очко, 1 = треть очка.
"""
import argparse
import json
import os
from collections import defaultdict


def load(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="road_value.jsonl")
    parser.add_argument("--out", default="road_value_summary.json")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"нет файла {args.file}")
        return 1
    rows = [r for r in load(args.file) if r.get("cost") is not None]
    print(f"строк с ценой шага: {len(rows)} "
          f"(всего строк в файле: {len(load(args.file))})")
    with_road = [r for r in rows if r.get("road_to")]
    print(f"шагов НА клетку с дорогой: {len(with_road)}")
    on_road = [r for r in rows if r.get("road_from")]
    print(f"шагов С клетки с дорогой: {len(on_road)}")

    by_pair = defaultdict(lambda: {"road": [], "plain": []})
    for row in rows:
        key = (row.get("terrain_from"), row.get("terrain_to"))
        by_pair[key]["road" if row.get("road_to") else "plain"].append(
            float(row["cost"]))
    print("\nпары «местность→местность»: цена (медиана, n)")
    med = {}
    for key in sorted(by_pair, key=lambda k: str(k)):
        data = by_pair[key]
        for kind in ("road", "plain"):
            values = sorted(data[kind])
            if not values:
                continue
            middle = values[len(values) // 2]
            med[(key, kind)] = middle
            print(f"  {str(key):32s} {kind:5s} медиана={middle:5.1f} n={len(values)}")

    # Пары, где есть ОБА класса — только они что-то решают.
    pairs = [(key, med[(key, 'road')], med[(key, 'plain')])
             for key in by_pair if med.get((key, "road")) and med.get((key, "plain"))]
    print(f"\nпар с обоими классами: {len(pairs)}")
    decided = 0
    ratios = []
    for key, road, plain in pairs:
        better = road < plain
        decided += 1 if better else 0
        ratios.append(road / plain if plain else float("nan"))
        print(f"  {str(key):32s} дорога={road:5.1f} без={plain:5.1f} "
              f"{'дорога дешевле' if better else 'не дешевле'}")
    verdict = "нет данных"
    if pairs:
        ratios_sorted = sorted(r for r in ratios if r == r)
        median_ratio = ratios_sorted[len(ratios_sorted) // 2] if ratios_sorted else None
        if decided >= 6 and median_ratio is not None and median_ratio <= 0.5:
            verdict = "H1 (дорога дешевле)"
        else:
            verdict = "H0 (дорога движению не помогает)"
        print(f"\nВЕРДИКТ: {verdict}; дешевле в {decided} из {len(pairs)} пар; "
              f"медиана отношения {median_ratio}")
    else:
        print("\nВЕРДИКТ: нет ни одной пары «дорога/без дороги» на одной местности. "
              "Это НЕ «дорога бесполезна» — это «дороги не было в замере»; "
              "нужен замер с построенной дорогой (или карта с дорогой).")
    # Отдельно — по классам «откуда→куда» с учётом дороги: шаг «дорога→дорога»
    # это и есть «идти ВДОЛЬ дороги», на котором сорвался прежний слабый замер.
    classes = defaultdict(list)
    for row in rows:
        key = (row.get("terrain_from"), row.get("terrain_to"),
               bool(row.get("road_from")), bool(row.get("road_to")))
        classes[key].append(float(row["cost"]))
    print("\nклассы шагов (дорога откуда/куда): цена (медиана, n)")
    for key in sorted(classes, key=lambda k: str(k)):
        values = sorted(classes[key])
        print(f"  {str(key):44s} медиана={values[len(values) // 2]:5.1f} "
              f"n={len(values)}")

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"rows": len(rows), "with_road": len(with_road),
                   "pairs": len(pairs), "decided": decided, "verdict": verdict},
                  handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
