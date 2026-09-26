"""Прогноз площадки против факта города: закрывает или опровергает модель.

Скрипт отвечает на один вопрос, и заранее допускает оба ответа.

Модель (`env/site_eval.py`) утверждает: выход города = сумма лучших `size+1`
клеток площадки, по каналам еда/щиты/торговля. Мир публикует фактический выход
(`prod_food`, `prod_shield`, `prod_trade`). Если модель верна — ошибка мала и
прогноз коррелирует с фактом; если неверна — корреляции нет, и это надо
сказать прямо, а не «уточнить коэффициент».

Корпус собирается живыми матчами (`env/site_outcomes.py`), поэтому N растёт от
прогона к прогону; сначала он мал, и первое, что выведет скрипт, — сколько
наблюдений есть на самом деле.

    python scripts/analyze_site_outcomes.py [--file site_outcomes.jsonl]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env.site_outcomes import CHANNELS, load, summarize  # noqa: E402

#: Ниже этого числа наблюдений вывод не делается вовсе — и это не формальность:
#: на 5 городах коэффициент корреляции может выглядеть любым.
MIN_N_FOR_VERDICT = 20

#: Корреляция ниже этой — «связи не видно» (не «модель верна, но слабо»).
WEAK_CORR = 0.3


def bootstrap_corr_ci(pairs: list[tuple[float, float]], n_resamples: int = 5000,
                      seed: int = 4242) -> tuple[float, float] | None:
    """Перцентильный bootstrap для корреляции Пирсона: r без иллюзий точности."""
    if len(pairs) < 3:
        return None
    rng = random.Random(seed)
    rs: list[float] = []
    for _ in range(n_resamples):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        xs = [p for p, _ in sample]
        ys = [o for _, o in sample]
        mx, my = st.mean(xs), st.mean(ys)
        sx = sum((x - mx) ** 2 for x in xs) ** 0.5
        sy = sum((y - my) ** 2 for y in ys) ** 0.5
        if not sx or not sy:
            continue
        rs.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy))
    if len(rs) < 100:
        return None
    rs.sort()
    return rs[int(0.025 * len(rs))], rs[int(0.975 * len(rs)) - 1]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", default="", help="корпус сверок (по умолчанию — общий)")
    p.add_argument("--json", action="store_true", help="машинный вывод")
    args = p.parse_args()

    rows = load(Path(args.file) if args.file else None)
    if not rows:
        print("Корпус пуст: сверок «прогноз площадки ↔ факт города» ещё нет.")
        print("Они появятся после живого матча (env/site_outcomes.py).")
        return 0

    usable = [r for r in rows if not r.get('lost') and r.get('pred_food') is not None]
    # Строки без метки прогона — не из живых матчей: их оставили тесты, которые
    # гоняют настоящий экстрактор. В вывод они не идут, и это не «очистка
    # данных», а отделение тестового мусора от измерений.
    untagged = [r for r in usable if not r.get('tag')]
    usable = [r for r in usable if r.get('tag')]
    lost = [r for r in rows if r.get('lost')]
    summary = summarize(usable)

    print("=" * 84)
    print("Прогноз площадки против факта города")
    print("=" * 84)
    print(f"  строк в корпусе: {len(rows)}  пригодных: {len(usable)}  "
          f"потерянных городов: {len(lost)}")
    if untagged:
        print(f"  отброшено тестовых строк (без метки прогона): {len(untagged)}")
    causes: dict[str, int] = {}
    for r in usable:
        causes[r.get('cause', '?')] = causes.get(r.get('cause', '?'), 0) + 1
    print(f"  откуда города: {causes}")
    tags: dict[str, int] = {}
    for r in usable:
        tags[str(r.get('tag', '—'))] = tags.get(str(r.get('tag', '—')), 0) + 1
    if len(tags) > 1:
        print(f"  по прогонам: {tags}")
    ages = [int(r.get('age', 0)) for r in usable]
    if ages:
        print(f"  возраст города при сверке: {min(ages)}–{max(ages)} ходов")
    sizes = [int(r.get('size', 0)) for r in usable]
    if sizes:
        print(f"  размер города при сверке: {min(sizes)}–{max(sizes)}")

    for channel in CHANNELS:
        stats = summary["channels"].get(channel, {})
        if not stats.get("n_usable"):
            print(f"\n  {channel}: нет пар, где факт не ноль — сравнивать нечего")
            continue
        pairs = [(float(r[f"pred_{channel}"]), float(r[f"obs_{channel}"]))
                 for r in usable
                 if r.get(f"pred_{channel}") is not None]
        pairs = [(a, b) for a, b in pairs if b]
        ci = bootstrap_corr_ci(pairs)
        print(f"\n  {channel}: пар {stats['n_usable']}, "
              f"прогноз в среднем {stats['pred_mean']:.2f} против факта "
              f"{stats['obs_mean']:.2f}")
        print(f"    относительная ошибка: средняя {stats['error_mean']:.3f}, "
              f"худшая {stats['error_max']:.3f}; точных совпадений "
              f"{stats['exact_share']:.0%}")
        if stats["corr"] is None:
            print("    корреляция: не определена (мало пар или нет разброса)")
        else:
            line = f"    корреляция прогноза с фактом: {stats['corr']:+.2f}"
            if ci:
                line += f"  95% CI [{ci[0]:+.2f}, {ci[1]:+.2f}]"
            print(line)
        if stats.get("gross_n"):
            gross_ci = bootstrap_corr_ci(
                [(float(r[f"pred_{channel}"]),
                  float(r[f"obs_{channel}"]) + float(r.get(
                      {"shield": "obs_waste", "trade": "obs_corruption"}.get(
                          channel, ""), 0) or 0))
                 for r in usable if r.get(f"pred_{channel}") is not None
                 and r.get(f"obs_{channel}") is not None])
            print(f"    БЕЗ вычета потерь (валовой факт): ошибка "
                  f"{stats['gross_error_mean']:.3f}, корреляция "
                  f"{stats['gross_corr']:+.2f}" if stats.get('gross_corr') is not None
                  else "    валовое сравнение: корреляция не определена",
                  end="")
            if gross_ci:
                print(f"  95% CI [{gross_ci[0]:+.2f}, {gross_ci[1]:+.2f}]")
            else:
                print()

    print()
    print("-" * 84)
    # Модель считает ПОТЕНЦИАЛ площадки (все size+1 клеток обрабатываются лучшим
    # образом), а мир публикует ФАКТИЧЕСКУЮ занятость: каких именно жителей куда
    # поставил губернатор, игра не сообщает. Поэтому «ошибка уровня» — это не
    # ошибка модели, а разница между потенциалом и занятостью, и утверждать по
    # ней «модель врёт на 41%» нельзя. Что проверяемо строго: (1) прогноз не
    # должен быть НИЖЕ факта (иначе это не потенциал) и (2) связь должна быть.
    for channel in CHANNELS:
        pairs = [(float(r[f"pred_{channel}"]), float(r[f"obs_{channel}"]))
                 for r in usable
                 if r.get(f"pred_{channel}") is not None and r.get(f"obs_{channel}")]
        pairs = [(p, o) for p, o in pairs if o]
        if not pairs:
            continue
        above = sum(1 for p, o in pairs if p >= o - 1e-9) / len(pairs)
        gaps = [p - o for p, o in pairs]
        print(f"{channel:>9}: прогноз ≥ факт в {above:.0%} случаев; "
              f"разрыв в среднем {sum(gaps)/len(gaps):+.2f} "
              f"(от {min(gaps):+.2f} до {max(gaps):+.2f})")
    print("  (если прогноз почти всегда ≥ факта и разрыв узкий — модель считает "
          "потенциал площадки, а не фактическую занятость клеток; тогда «ошибка "
          "уровня» измеряет неверность сравнения, а не модели)")

    with_mood = [r for r in usable if r.get('obs_unhappy') is not None
                 and r.get('pred_food') is not None and r.get('obs_food')]
    if len(with_mood) >= 5:
        def _bias(rows_: list[dict]):
            if not rows_:
                return None
            vals = [(float(r['pred_food']) - float(r['obs_food'])) / float(r['obs_food'])
                    for r in rows_]
            return sum(vals) / len(vals)

        upset = [r for r in with_mood
                 if (r.get('obs_unhappy') or 0) + (r.get('obs_angry') or 0) > 0]
        calm = [r for r in with_mood
                if (r.get('obs_unhappy') or 0) + (r.get('obs_angry') or 0) == 0]
        b_up, b_calm = _bias(upset), _bias(calm)
        if b_up is not None and b_calm is not None:
            print(f"Перекос прогноза по еде: с недовольными {b_up:+.3f} "
                  f"(n={len(upset)}), без недовольных {b_calm:+.3f} (n={len(calm)})")
            if abs(b_up - b_calm) < 0.05:
                print("  → гипотеза НЕ подтверждается: перекос одинаков, значит "
                      "дело в самой модели площадки, а не в неработающих жителях")
            elif b_up > b_calm:
                print("  → согласуется с гипотезой: перекос сильнее там, где есть "
                      "недовольные (модель считает работающими всех)")
            else:
                print("  → обратное ожиданию: перекос сильнее БЕЗ недовольных")
    print()
    if len(usable) < MIN_N_FOR_VERDICT:
        print(f"ВЫВОД: пока нельзя. Наблюдений {len(usable)}, нужно хотя бы "
              f"{MIN_N_FOR_VERDICT}: на малом N корреляция и ошибка сами по себе "
              "ничего не доказывают. Прогонов надо больше, и это не оговорка — "
              "это условие.")
    else:
        food = summary["channels"].get("food", {})
        corr = food.get("corr")
        if corr is None:
            print("ВЫВОД: корреляция по еде не определена (нет разброса в данных).")
        elif abs(corr) < WEAK_CORR:
            print(f"ВЫВОД: НЕ ПОДТВЕРЖДЕНО. На {len(usable)} городах связь прогноза "
                  f"с фактом по еде r = {corr:+.2f} — ниже порога {WEAK_CORR}. "
                  "Модель площадок в этой форме предсказательной силы не показала; "
                  "это её опровергает, а не «уточняет коэффициент».")
        else:
            print(f"ВЫВОД: подтверждено на {len(usable)} городах: r = {corr:+.2f} "
                  f"по еде, средняя относительная ошибка {food['error_mean']:.3f}. "
                  "Но CI выше показывает, насколько это ещё неточно.")
    if args.json:
        print(json.dumps({"summary": summary, "lost": len(lost)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
