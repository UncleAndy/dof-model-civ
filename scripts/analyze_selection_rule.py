"""Какое правило назначения жителей воспроизводит наблюдение.

Сравниваются два семейства гипотез на одних и тех же городах:

* `per_channel` — лучший набор клеток для каждого канала отдельно (так делает
  модель площадки);
* `single_*` — один набор клеток на город (например, «сначала еда, потом щиты»),
  и все три канала считаются по нему.

Если наблюдение воспроизводит какое-то `single_*`, значит модель брала неверный
набор и именно поэтому щиты и торговля завышались. Если ни одно — дело не в
наборе, и это тоже результат.

Считаются только строки, где **все 21 клетка разведаны**: на неразведанной карте
сравнивать нечего, а подстановка среднего сделала бы различия между правилами
неразличимыми. Сколько строк отброшено по этой причине — печатается.

    python scripts/analyze_selection_rule.py [--file site_outcomes.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env.site_eval import CITY_CENTRE_MIN  # noqa: E402
from env.site_outcomes import load  # noqa: E402
from env.site_rules import PER_CHANNEL_RULE, all_rules, predict, verdict  # noqa: E402

CHANNELS = ("еда", "щиты", "торговля")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", default="")
    p.add_argument("--tol", type=float, default=1e-9,
                   help="допуск совпадения прогноза с фактом")
    args = p.parse_args()

    rows = load(Path(args.file) if args.file else None)
    usable = []
    skipped_unknown = 0
    skipped_no_field = 0
    for r in rows:
        if r.get("lost") or r.get("size") is None or r.get("obs_food") is None:
            continue
        if not r.get("tiles"):
            # Строки, собранные до того, как корпус начал писать клетки. Их нельзя
            # молча терять: иначе «0 пригодных» будет выглядеть как «правило не
            # найдено», хотя это «сырья нет».
            skipped_no_field += 1
            continue
        if len(r["tiles"]) < 21 or sum(1 for k in (r.get("tiles_known") or []) if not k):
            skipped_unknown += 1
            continue
        usable.append(r)

    print("=" * 86)
    print("Правило назначения жителей: какое воспроизводит факт")
    print("=" * 86)
    print(f"  строк в корпусе: {len(rows)}  пригодных (вся площадка разведана): "
          f"{len(usable)}")
    print(f"  отброшено: без клеток в строке (старый корпус): {skipped_no_field}; "
          f"часть клеток не разведана: {skipped_unknown}")
    if not usable:
        print("\nНет пригодных строк — вердикта нет. Это не «правило не найдено»,"
              " это «данных нет».")
        return 0

    print()
    header = f"{'правило':<26}" + "".join(f"{c:>19}" for c in CHANNELS)
    print(header)
    print(f"{'':<26}" + "".join(f"{'точных / ошибка':>19}" for _ in CHANNELS))
    print("-" * 86)
    best = None
    exact_by_rule: dict[str, list[int]] = {}
    for rule in all_rules():
        exact = [0, 0, 0]
        err = [0.0, 0, 0]  # сумма |прогноз − факт|
        for r in usable:
            got = predict([tuple(t) for t in r["tiles"]], int(r["size"]), rule)
            for ch, observed in enumerate((r["obs_food"], r["obs_shield"],
                                           r["obs_trade"])):
                try:
                    observed = float(observed)
                except (TypeError, ValueError):
                    continue
                if abs(got[ch] - observed) <= args.tol:
                    exact[ch] += 1
                err[ch] += abs(got[ch] - observed)
        n = len(usable)
        cells = "".join(f"{exact[ch]/n:>10.0%}/{err[ch]/n:>8.2f}" for ch in range(3))
        print(f"{rule:<26}{cells}")
        exact_by_rule[rule] = exact
        hits = sum(exact)
        if best is None or hits > best[1]:
            best = (rule, hits, exact)

    print()
    v = verdict(exact_by_rule, len(usable))
    if v["ok"]:
        print(f"ВЕРДИКТ: {v['reason']}")
        if v["rule"] != PER_CHANNEL_RULE:
            print("  → правило ОДНОГО набора клеток. Значит модель брала неверный"
                  " набор: она давала каждому каналу его лучшие клетки, а игра"
                  " обрабатывает один набор и берёт из него все три канала.")
        else:
            print("  → подтверждается текущая модель: игре выгоден свой набор на"
                  " каждый канал. Тогда провал щитов и торговли имеет другую причину.")
    else:
        print(f"ВЕРДИКТА НЕТ: {v['reason']}")
        print(f"  (лучшим по таблице было `{best[0]}` — {best[1]} точных"
              f" совпадений из {3 * len(usable)}; этого мало, чтобы утверждать"
              f" правило, и я этого не утверждаю)")
    print()
    print("Оговорки: сравниваются только полностью разведанные площадки; наборы"
          " проверяются по значениям клеток, без координат; факт берётся как есть"
          " (включая недовольных, которые не работают). Центр берётся с поправкой"
          f" «не меньше {CITY_CENTRE_MIN:g}» по каждому каналу — без неё факт"
          " вообще не раскладывается на клетки (измерено: 1 из 8 строк против 6"
          " из 8).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
