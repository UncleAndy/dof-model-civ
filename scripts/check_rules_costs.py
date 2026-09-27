#!/usr/bin/env python
"""Есть ли в наблюдении стоимость технологий и улучшений?

Нужно, чтобы не повторять историю с производством: там «очевидный» вывод
(`prod_shield / prod_process`) оказался неверным, и правильную формулу дал только
замер. Поэтому проверяем по файлу наблюдения, какие числа мир отдаёт САМ:

* технология: срок — это `стоимость / bulbs_за_ход`; есть ли стоимость и выход
  науки в наблюдении (`tech`, `player`, `city`);
* улучшение: стоимость — есть ли она в спецификациях технологий
  (`sup_improvements[].build_cost`), как это было у юнитов (`sup_units[].build_cost`).

    python scripts/check_rules_costs.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TECH_HINTS = ("cost", "beaker", "bulb", "research", "turns", "progress", "science")


def main() -> int:
    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]

    tech = obs.get("tech") or {}
    print(f"технологий в наблюдении: {len(tech)}")
    names = sorted(t for t in tech if isinstance(tech[t], dict))
    for name in names[:3]:
        rec = tech[name]
        print(f"\n=== технология «{name}» — ключи:")
        print("   ", sorted(rec.keys()))
        for key in sorted(rec.keys()):
            low = key.lower()
            if any(hint in low for hint in TECH_HINTS):
                print(f"    {key} = {json.dumps(rec[key], default=str)[:200]}")

    # Любые поля со стоимостью у всех технологий: ищем не по одной, а по всем.
    print("\nсопоставление по всем технологиям (поля с 'cost'/'bulb'/'turn'):")
    seen: dict[str, list] = {}
    for name, rec in tech.items():
        if not isinstance(rec, dict):
            continue
        for key, value in rec.items():
            low = key.lower()
            if any(hint in low for hint in TECH_HINTS):
                seen.setdefault(key, []).append(value)
    for key, values in sorted(seen.items()):
        sample = [v for v in values[:5]]
        print(f"   {key}: {len(values)} значений, примеры {sample}")

    print("\n=== спецификации улучшений в технологиях (build_cost?):")
    shown = 0
    for name, rec in tech.items():
        if not isinstance(rec, dict):
            continue
        for spec in (rec.get("sup_improvements") or []):
            if isinstance(spec, dict):
                keys = sorted(spec.keys())
                print(f"   {name}: {keys}")
                print(f"      build_cost={spec.get('build_cost')} "
                      f"name={spec.get('name')!r} rule_name={spec.get('rule_name')!r}")
                shown += 1
                break
        if shown >= 3:
            break
    if not shown:
        print("   спецификаций улучшений со стоимостью НЕ найдено")

    print("\n=== наука у игрока и города:")
    for pid, player in (obs.get("player") or {}).items():
        if isinstance(player, dict):
            keys = [k for k in sorted(player) if any(
                hint in k.lower() for hint in ("bulb", "science", "research", "gold",
                                              "tax", "lux"))]
            print(f"   player {pid}: {[(k, player[k]) for k in keys][:8]}")
    for cid, city in (obs.get("city") or {}).items():
        if isinstance(city, dict):
            keys = [k for k in sorted(city) if any(
                hint in k.lower() for hint in ("bulb", "science", "prod", "shield",
                                              "improve"))]
            print(f"   city {cid}: {[(k, json.dumps(city[k], default=str)[:40]) for k in keys][:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
