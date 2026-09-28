#!/usr/bin/env python
"""Сверка цены перевода жителя: наблюдённая дельта против предсказания формулы.

Правило объявлено в §10.25: цена перевода — разница формулы города до и после.
Предсказание считается так, как его считал бы прогноз: берём запись города ДО, сдвигаем
её каналы на разницу выходов клеток (из слоя карты, тот же источник, что у прогноза) и
считаем `city_options`. Наблюдённая дельта — из строки замера.

Помехи называются прямо, а не прячутся:
* размер города: если он изменился, дельта включает рост (новый житель), и строка
  помечается как загрязнённая;
* производство: замер идёт с `--no-buy` (очередь не трогаем), но сама очередь может
  достроиться в окне — тогда меняются щиты, и это тоже видно в строке.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from env.entity_extractor import city_options  # noqa: E402


def shifted(rec, delta):
    """Запись города со сдвинутыми каналами на разницу выходов клеток."""
    out = dict(rec)
    for field, index in (("prod_food", 0), ("prod_shield", 1), ("prod_trade", 2),
                         ("surplus_food", 0), ("surplus_shield", 1),
                         ("surplus_trade", 2)):
        try:
            out[field] = float(rec.get(field) or 0.0) + delta[index]
        except (TypeError, ValueError):
            continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="buy_and_work_work.jsonl")
    args = parser.parse_args()

    rows = [json.loads(line) for line in open(args.file, encoding="utf-8")
            if line.strip()]
    pairs = {}
    for row in rows:
        if row.get("kind") != "pair":
            continue
        key = (row.get("city"), row.get("action"))
        # Оставляем первую (самую раннюю) выборку пары: дальше окно уже дрейфует.
        if key not in pairs or row["since"] < pairs[key]["since"]:
            pairs[key] = row
    posts = {}
    for row in rows:
        if row.get("kind") in ("work_post", "unwork_post"):
            posts.setdefault((row.get("city"), row.get("action")), row)

    print(f"{'город':>7} {'срок':>5} {'размер':>7} {'предсказание':>13} "
          f"{'наблюдение':>11} {'разница':>9}  пометка")
    for key, row in sorted(pairs.items()):
        before = {k[len("before_"):]: v for k, v in row.items()
                  if k.startswith("before_")}
        observed = row.get("delta_options")
        # Выходы клеток лежат в строках постановки.
        work_post = None
        for prow in rows:
            if prow.get("kind") == "work_post" and prow.get("action") == row.get("action"):
                work_post = prow
        to_out = (work_post or {}).get("tile_to_output") or (work_post or {}).get("tile_to_output")
        from_out = (work_post or {}).get("tile_from_output")
        predicted = None
        if to_out and from_out and all(isinstance(v, (int, float)) for v in to_out + from_out):
            delta = [to_out[i] - from_out[i] for i in range(3)]
            try:
                predicted = round(city_options(shifted(before, delta))
                                  - city_options(before), 4)
            except Exception:  # noqa: BLE001
                predicted = None
        size_before = before.get("size")
        size_after = row.get("after_size")
        note = []
        if size_before != size_after:
            note.append("рост города (загрязнено)")
        if row.get("since", 0) > 1:
            note.append(f"окно {row.get('since')} ходов")
        diff = (None if predicted is None or observed is None
                else round(observed - predicted, 4))
        print(f"{str(row.get('city')):>7} {row.get('since'):>5} "
              f"{str(size_before)}→{str(size_after):>2} "
              f"{('—' if predicted is None else f'{predicted:+.4f}'):>13} "
              f"{('—' if observed is None else f'{observed:+.4f}'):>11} "
              f"{('—' if diff is None else f'{diff:+.4f}'):>9}  {', '.join(note)}")
    print("\n(предсказание = формула города со сдвигом каналов по выходам клеток; "
          "наблюдение = поля города до/после пары; совпадение знака/величины — то, что "
          "проверяется, а не подгоняется)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
