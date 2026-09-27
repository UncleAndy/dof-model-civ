#!/usr/bin/env python
"""Есть ли параметры типов юнитов в правилах наблюдения?

От этого зависит, можно ли оценить тип, которого нет живьём: опции типа считаются по
его параметрам (`unit_options`), и если правилсет их отдаёт, круг «нет живого юнита —
нет цены» разрывается без всяких замеров.

    python scripts/check_rules_unit_types.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]

    rules = obs.get("rules") or {}
    print(f"ключей в rules: {len(rules)}")
    print("имена с 'unit'/'type'/'cost':")
    for key in sorted(rules):
        low = key.lower()
        if "unit" in low or "type" in low or "cost" in low:
            print(f"   {key} = {json.dumps(rules[key], default=str)[:120]}")

    tech = obs.get("tech") or {}
    print(f"\nключей в tech: {len(tech)}")
    sample = next(iter(tech.values()), None)
    if isinstance(sample, dict):
        print(f"пример записи технологии: {json.dumps(sample, default=str)[:400]}")
    gov = obs.get("gov") or {}
    print(f"\nключей в gov: {len(gov)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
