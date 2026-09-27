#!/usr/bin/env python
"""Сводка пробы улучшений: цена, срок сервера и ФАКТИЧЕСКАЯ скорость накопления.

Вопрос, который решает эта сводка: можно ли срок улучшения считать так же, как у
юнитов (`ceil((стоимость − stock) / prod_shield)`)? На живых данных первых двух
постановок получилось иначе: сервер обещал ~`стоимость − stock` ходов, то есть
примерно 1 щит за ход, при публикуемом `prod_shield` 5–7. Здесь это проверяется
наблюдением: по строкам `watch` видно, на сколько растёт готовность за ход.

Никаких порогов «на глаз»: печатаются сами числа по каждому улучшению.
"""
import argparse
import json
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
    parser.add_argument("--file", default="improvement_probe.jsonl")
    args = parser.parse_args()
    rows = load(args.file)
    menus = [r for r in rows if r.get("kind") == "menu"]
    for row in menus:
        print(f"меню города (ход {row.get('turn')}): {row.get('produce')}")
    posts = [r for r in rows if r.get("kind") == "post"]
    print(f"\nпостановок: {len(posts)}")
    watches = defaultdict(list)
    for row in rows:
        if row.get("kind") == "watch":
            watches[(row.get("wanted"), row.get("city"))].append(row)

    for (wanted, city), series in watches.items():
        series.sort(key=lambda r: r.get("since_post") or 0)
        print(f"\n=== {wanted} (город {city}), наблюдений: {len(series)}")
        prev_proc = None
        prev_stock = None
        for row in series:
            proc = row.get("prod_process")
            stock = row.get("shield_stock")
            shields = row.get("prod_shield")
            turns = row.get("turns_to_prod_complete")
            cost = round(stock / proc, 1) if proc and stock else None
            dproc = None if prev_proc is None or proc is None else round(proc - prev_proc, 6)
            dstock = None if prev_stock is None or stock is None else round(stock - prev_stock, 3)
            print(f"  +{row.get('since_post')}: щиты/ход={shields} stock={stock} "
                  f"готовность={proc} стоимость={cost} срок_сервера={turns} "
                  f"Δготовность={dproc} Δstock={dstock}")
            prev_proc, prev_stock = proc, stock
        # Проверка: срок сервера против «стоимость − stock» и против варианта с щитами.
        first = series[0]
        if first.get("prod_process") and first.get("shield_stock") is not None:
            cost = first["shield_stock"] / first["prod_process"]
            stock = first["shield_stock"]
            rate1 = cost - stock
            rate_s = ((cost - stock) / first["prod_shield"]
                      if first.get("prod_shield") else None)
            print(f"  ВЕРДИКТ по сроку: сервер={first.get('turns_to_prod_complete')} "
                  f"vs «стоимость−stock»={rate1:.1f} "
                  f"vs «(стоимость−stock)/prod_shield»="
                  f"{rate_s if rate_s is None else round(rate_s, 1)}")
    if not watches:
        print("наблюдений нет — постановка не состоялась (улучшение не предлагалось)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())