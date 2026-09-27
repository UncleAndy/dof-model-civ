#!/usr/bin/env python
"""Какие поля живого юнита называют его ТИП (имя, а не только параметры)?

Нужно затем, чтобы оценить тип производства: у типа есть опции и стоимость, но взять
их можно только по имени (`produce_<Тип>` — это имя). Если у живого юнита имени нет,
этот источник цен недоступен, и остаётся только каталог извлекателя.

    python scripts/check_unit_type_fields.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]
    units = obs.get("unit") or {}
    print(f"живых юнитов: {len(units)}")
    for uid, unit in list(units.items())[:4]:
        if not isinstance(unit, dict):
            continue
        print(f"\nюнит {uid}: ключи")
        print("  " + ", ".join(sorted(unit.keys())))
        named = {k: unit[k] for k in unit
                 if k in ("rule_name", "type_rule_name", "type_name", "name", "type")}
        print(f"  поля-имена: {named}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
