"""A/B: надбавка за незнание включена против выключенной.

Вопрос, на который отвечает скрипт: **окупается ли любопытство**. Агент с
надбавкой тратит ходы на пробы неизмеренных действий; агент без неё те же ходы
тратит на известную пользу. Разница в метриках — и есть цена/выигрыш механизма.

Как читать результат честно:
* слот = карта, поэтому сравнивать надо **пары по слоту** (paired): один и тот
  же мир, разные настройки. Пары, которых не случилось (варианты играли разные
  слоты), в paired-анализ не попадают — и скрипт говорит, сколько их;
* при малом N (6) CI широкий, и «CI включает 0» — это «данных не хватает», а не
  «эффекта нет». Так и написано в выводе;
* матч, убитый клинчем, — тоже результат: он показывает цену исследования. Он
  не выбрасывается молча, а попадает в отдельную строку.

    python scripts/analyze_curiosity_ab.py --off ab_curiosity_off.json \
                                           --on ab_curiosity_on.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics.stats import bootstrap_diff_ci, ci95, cohens_d, mean  # noqa: E402

#: Метрики, по которым сравниваем. Знак трактуем так: «больше — лучше», кроме
#: IrrRat, где меньше — лучше (необратимое действие тратит опции без возврата).
METRICS = [
    ("turns", "ходов сыграно"),
    ("avg_total_dof_index", "индекс DoF (средн.)"),
    ("irreversibility_ratio", "доля необратимых"),
    ("decisions_per_turn_mean", "решений на ход"),
    ("experiments_total", "попыток-экспериментов"),
    ("pairs_total", "пар «прогноз↔факт»"),
]


def load(path: str) -> tuple[list[dict], dict]:
    payload = json.loads(Path(path).read_text())
    results = payload.get("results", {})
    records: list[dict] = []
    for agent_records in results.values():
        records.extend(agent_records)
    return records, payload.get("meta", {})


def ok(records: list[dict]) -> list[dict]:
    """Матчи, которые доигрались: ошибки и клинчи считаем отдельно."""
    return [r for r in records if not r.get("error")]


def is_valid(r: dict, min_turns: int) -> bool:
    """Годится ли матч для сравнения.

    Матч, который кончился на 5-м ходу с пустым миром (`min_entities == 0`), —
    это не «агент сыграл плохо», это стенд не отдал игру (переиспользованный
    слот, который Publite2 не успел перезапустить). Такой матч нельзя
    засчитывать: его низкий индекс попал бы в средние как «цена любопытства».
    """
    if r.get("error") or r.get("wedge_action"):
        return False
    if float(r.get("turns") or 0) < min_turns:
        return False
    if float(r.get("min_entities") or 0) <= 0:
        return False
    return True


def by_port(records: list[dict]) -> dict[int, dict]:
    return {r["port"]: r for r in records if r.get("port") is not None}


def values(records: list[dict], key: str) -> list[float]:
    return [float(r.get(key) or 0.0) for r in records]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--off", default="ab_curiosity_off.json")
    p.add_argument("--on", default="ab_curiosity_on.json")
    p.add_argument("--min-turns", type=int, default=20,
                   help="матч короче этого числа ходов считается несостоявшимся")
    p.add_argument("--why", type=str, default="",
                   help="подзаголовок: чем этот прогон отличается от другого")
    args = p.parse_args()

    off_all, off_meta = load(args.off)
    on_all, on_meta = load(args.on)
    off = [r for r in off_all if is_valid(r, args.min_turns)]
    on = [r for r in on_all if is_valid(r, args.min_turns)]

    print("=" * 78)
    print("A/B: надбавка за незнание" + (f" — {args.why}" if args.why else ""))
    print("=" * 78)
    for label, all_records, kept in (("без", off_all, off), ("с", on_all, on)):
        print(f"  {label} любопытства: {len(all_records)} матчей, "
              f"пригодно {len(kept)}")
        for r in all_records:
            if r.get("wedge_action"):
                w = r["wedge_action"]
                print(f"    [клинч] слот {r.get('port')}: {w['ctrl_type']}/"
                      f"{w['action_name']} на ходу {w['turn']}")
            elif r.get("error"):
                print(f"    [ошибка] слот {r.get('port')}: {r['error']}")
            elif not is_valid(r, args.min_turns):
                # Не прячем: несостоявшийся матч — это факт о стенде, который
                # иначе испортил бы вывод о механизме.
                print(f"    [несостоявшийся] слот {r.get('port')}: ходов "
                      f"{r.get('turns')}, минимум сущностей {r.get('min_entities')}"
                      " — стенд не отдал игру")

    print()
    print(f"{'метрика':<26}{'без':>10}{'с':>10}{'разница':>10}{'95% CI':>20}")
    print("-" * 78)
    for key, label in METRICS:
        a, b = values(off, key), values(on, key)
        if not a or not b:
            continue
        lo, hi, diff = bootstrap_diff_ci(b, a)
        # With one or two matches per side the bootstrap CI collapses to a point
        # and would scream "significant" about nothing. Say "not enough data".
        star = "  <- значимо" if (lo > 0 or hi < 0) and min(len(a), len(b)) >= 4 else ""
        print(f"{label:<26}{mean(a):>10.3f}{mean(b):>10.3f}{diff:>10.3f}"
              f"{f'[{lo:+.3f}, {hi:+.3f}]':>20}{star}")

    # Paired by slot: the same map, so map quality cancels out. This is the only
    # comparison that isolates the mechanism rather than the map.
    off_by_port, on_by_port = by_port(off), by_port(on)
    pairs = [(port, off_by_port[port], on_by_port[port])
             for port in sorted(set(off_by_port) & set(on_by_port))]
    print()
    if len(pairs) < 2:
        print(f"Пар по слоту: {len(pairs)} — для paired-анализа мало. Выводы ниже"
              " только описательные.")
    else:
        print(f"Пар по слоту: {len(pairs)} (один и тот же мир, разные настройки)")
        print(f"{'метрика':<26}{'без':>10}{'с':>10}{'Δ средн.':>10}{'95% CI Δ':>20}")
        print("-" * 78)
        for key, label in METRICS:
            diffs = [float(o.get(key) or 0.0) - float(f.get(key) or 0.0)
                     for _, f, o in pairs]
            lo, hi = ci95(diffs)
            star = "  <- значимо" if (lo > 0 or hi < 0) and len(diffs) >= 4 else ""
            print(f"{label:<26}{mean([float(f.get(key) or 0.0) for _, f, _ in pairs]):>10.3f}"
                  f"{mean([float(o.get(key) or 0.0) for _, _, o in pairs]):>10.3f}"
                  f"{mean(diffs):>10.3f}{f'[{lo:+.3f}, {hi:+.3f}]':>20}{star}")
        a = [float(f.get("avg_total_dof_index") or 0.0) for _, f, _ in pairs]
        b = [float(o.get("avg_total_dof_index") or 0.0) for _, _, o in pairs]
        print(f"\n  d Коэна по индексу DoF (paired, N={len(pairs)}): {cohens_d(b, a):+.2f}")

    print()
    print("Оговорки, которые надо держать в голове при чтении:")
    print(" * N=6 слотов на вариант — CI широкий; «CI включает 0» значит «данных")
    print("   мало», а не «эффекта нет».")
    print(" * Слот = отдельная карта, поэтому и сравниваем по парам слотов.")
    print(" * Матч, убитый клинчем, — цена исследования, а не ошибка измерения:")
    print("   он вычтен из средних и показан отдельно.")
    sw = off_meta.get("curiosity"), on_meta.get("curiosity")
    print(f" * В метаданных прогонов: curiosity без = {sw[0]}, с = {sw[1]}"
          " (должно быть False и True).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
