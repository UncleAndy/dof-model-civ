"""A/B: надбавка за незнание включена против выключенной — по вкладу агента.

Две ловушки, обе найдены на живых данных, и обе определяют, как считать.

1. **Индекс DoF измеряет состояние мира, а мир растёт сам.** Простаивающий агент
   (0,1 решения на ход) набирает хороший индекс, потому что экономика
   компаундится: метрика вознаграждает бездействие. Поэтому вклад считается
   **относительно мира без агента** (`--noop`).
2. **«Пара по слоту» не существует.** Предполагалось, что один слот = одна карта
   и повторный прогон на нём даёт тот же мир. Измерено обратное: три прогона на
   одном слоте дали три разных старта — (7,43), (21,11), (42,29). Каждый матч —
   своя среда, поэтому сравнение только по распределениям, а не по парам, и
   `start_fingerprint` фиксирует, совпали ли старты на самом деле (обычно нет).

Что это значит для вывода: разброс между матчами (в том числе у no-op) —
это шум среды. Если разница между вариантами меньше этого разброса, вывода нет,
и скрипт говорит это прямо, а не выдаёт точку оценки за эффект.

    python scripts/analyze_curiosity_ab.py --off off.json --on on.json \
                                           --noop noop.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics.stats import bootstrap_diff_ci, ci95, cohens_d, mean  # noqa: E402

METRICS = [
    ("turns", "ходов сыграно"),
    ("irreversibility_ratio", "доля необратимых"),
    ("decisions_per_turn_mean", "решений на ход"),
    ("experiments_total", "попыток-экспериментов"),
    ("pairs_total", "пар «прогноз↔факт»"),
]


def load(path: str) -> tuple[list[dict], dict]:
    payload = json.loads(Path(path).read_text())
    records: list[dict] = []
    for agent_records in payload.get("results", {}).values():
        records.extend(agent_records)
    return records, payload.get("meta", {})


def is_valid(r: dict, min_turns: int) -> bool:
    """Матч, кончившийся на 5-м ходу с пустым миром, — это стенд не отдал игру
    (занятый или доигранный слот), а не «агент сыграл плохо». Его нельзя
    засчитывать: низкий индекс попал бы в средние как свойство агента."""
    if r.get("error") or r.get("wedge_action"):
        return False
    return (float(r.get("turns") or 0) >= min_turns
            and float(r.get("min_entities") or 0) > 0)


def values(records: list[dict], key: str) -> list[float]:
    return [float(r.get(key) or 0.0) for r in records]


def fmt(values_list: list[float]) -> str:
    if not values_list:
        return "—"
    lo, hi = ci95(values_list)
    return f"{mean(values_list):+.3f} [{lo:+.3f}, {hi:+.3f}]"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--off", default="ab_curiosity_off.json")
    p.add_argument("--on", default="ab_curiosity_on.json")
    p.add_argument("--noop", default="", help="прогон агента no-op (мир без агента)")
    p.add_argument("--min-turns", type=int, default=20)
    p.add_argument("--why", type=str, default="")
    args = p.parse_args()

    off_all, off_meta = load(args.off)
    on_all, on_meta = load(args.on)
    off = [r for r in off_all if is_valid(r, args.min_turns)]
    on = [r for r in on_all if is_valid(r, args.min_turns)]
    noop: list[dict] = []
    if args.noop:
        noop_all, _ = load(args.noop)
        noop = [r for r in noop_all if is_valid(r, args.min_turns)]

    print("=" * 88)
    print("A/B: надбавка за незнание" + (f" — {args.why}" if args.why else ""))
    print("=" * 88)
    for label, all_records, kept in (("без", off_all, off), ("с", on_all, on)):
        print(f"  {label} любопытства: {len(all_records)} матчей, пригодно {len(kept)}")
        for r in all_records:
            if r.get("wedge_action"):
                w = r["wedge_action"]
                print(f"    [клинч] слот {r.get('port')}: {w['ctrl_type']}/"
                      f"{w['action_name']} на ходу {w['turn']}")
            elif r.get("error"):
                print(f"    [ошибка] слот {r.get('port')}: {r['error']}")
            elif not is_valid(r, args.min_turns):
                print(f"    [несостоявшийся] слот {r.get('port')}: ходов "
                      f"{r.get('turns')}, минимум сущностей {r.get('min_entities')}"
                      " — стенд не отдал игру")

    # Show, without commentary, that each match really is its own environment.
    for label, kept in (("без", off), ("с", on), ("no-op", noop)):
        starts = [tuple(r.get("start_xy") or ()) for r in kept if r.get("start_xy")]
        if starts:
            uniq = len(set(starts))
            print(f"  старты ({label}): {uniq} различных из {len(starts)} матчей"
                  + ("  ← совпадений нет, парность невозможна"
                     if uniq == len(starts) and uniq > 1 else ""))

    print()
    print(f"{'метрика':<26}{'без':>12}{'с':>12}{'разница':>10}{'95% CI':>22}")
    print("-" * 88)
    for key, label in METRICS:
        a, b = values(off, key), values(on, key)
        if not a or not b:
            continue
        lo, hi, diff = bootstrap_diff_ci(b, a)
        star = "  <- значимо" if (lo > 0 or hi < 0) and min(len(a), len(b)) >= 4 else ""
        print(f"{label:<26}{mean(a):>12.3f}{mean(b):>12.3f}{diff:>10.3f}"
              f"{f'[{lo:+.3f}, {hi:+.3f}]':>22}{star}")

    print()
    print("ИНДЕКС DoF: состояние мира против вклада агента")
    a_idx, b_idx = values(off, "avg_total_dof_index"), values(on, "avg_total_dof_index")
    lo, hi, diff = bootstrap_diff_ci(b_idx, a_idx)
    star = "  <- значимо" if (lo > 0 or hi < 0) and min(len(a_idx), len(b_idx)) >= 4 else ""
    print(f"  {'без (состояние)':<26}{fmt(a_idx):>28}")
    print(f"  {'с (состояние)':<26}{fmt(b_idx):>28}")
    print(f"  {'разница состояний':<26}{diff:>+28.3f}  95% CI "
          f"[{lo:+.3f}, {hi:+.3f}]{star}")
    if len(a_idx) >= 2 and len(b_idx) >= 2:
        print(f"  d Коэна по состоянию: {cohens_d(b_idx, a_idx):+.2f}")

    if noop:
        n_idx = values(noop, "avg_total_dof_index")
        print()
        print("МИР БЕЗ АГЕНТА (no-op) — планка и шум среды")
        print(f"  индекс no-op: {fmt(n_idx)}  (матчей {len(n_idx)})")
        if len(n_idx) >= 2:
            print(f"  разброс среды: мин {min(n_idx):.2f}, макс {max(n_idx):.2f}, "
                  f"σ {statistics.stdev(n_idx):.2f}")
        base = mean(n_idx)
        n_turns = mean(values(noop, "turns"))
        print(f"  средняя длина no-op: {n_turns:.1f} ходов")
        att_off = [v - base for v in a_idx]
        att_on = [v - base for v in b_idx]
        print(f"  вклад без надбавки: {fmt(att_off)}")
        print(f"  вклад с надбавкой : {fmt(att_on)}")
        lo, hi, diff = bootstrap_diff_ci(att_on, att_off)
        star = "  <- значимо" if (lo > 0 or hi < 0) and min(len(att_on), len(att_off)) >= 4 else ""
        print(f"  Δ вклада: {diff:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]{star}")
        if len(n_idx) >= 2:
            spread = max(n_idx) - min(n_idx)
            print(f"  ВНИМАНИЕ: разброс среды {spread:.2f}. Если |Δ вклада| меньше,"
                  " он не отличим от того, куда нас поставили, а не от того,"
                  " что мы делали.")
        # With a fixed horizon (which the long run has), how much of the
        # difference is just "no-op also reaches turn N"? Reported, not hidden.
        print(f"  (матчи фиксированного горизонта: у no-op {min(values(noop, 'turns')):.0f}"
              f"–{max(values(noop, 'turns')):.0f} ходов, у вариантов "
              f"{min(values(off + on, 'turns')):.0f}–{max(values(off + on, 'turns')):.0f})")

    print()
    print("Оговорки:")
    print(" * Каждый матч — своя среда (старты не повторяются), парности нет:")
    print("   сравниваем распределения, а не пары.")
    print(" * «CI включает 0» = «данных мало», а не «эффекта нет».")
    print(" * Индекс измеряет состояние мира; решает вклад относительно no-op.")
    print(" * Несостоявшийся матч и клинч — факты о стенде, не о механизме.")
    print(f" * Метаданные: curiosity без = {off_meta.get('curiosity')}, "
          f"с = {on_meta.get('curiosity')}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
