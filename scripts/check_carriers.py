#!/usr/bin/env python
"""Кто из живых юнитов считается носителем населения — и почему.

От этого зависят семейства «основание» и «движение»: если `is_carrier` ложно,
носитель не получает ни цены площадки, ни права основать город, и прогноз видит
только работы.

Проверка на реальном наблюдении (офлайн).

    python scripts/check_carriers.py
"""
import inspect
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def main() -> int:
    import warnings
    warnings.filterwarnings("ignore")

    from env.entity_extractor import is_population_carrier

    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]

    try:
        print("исходник is_population_carrier:")
        print("   " + "\n   ".join(
            line.strip() for line in
            inspect.getsource(is_population_carrier).splitlines()[:18]))
    except Exception as exc:  # noqa: BLE001
        print(f"   (не прочитать: {exc})")

    for uid, unit in (obs.get("unit") or {}).items():
        if not isinstance(unit, dict):
            continue
        print(f"юнит {uid} ({unit.get('type_rule_name')}): "
              f"is_carrier={is_population_carrier(unit)} "
              f"type_worker={unit.get('type_worker')} "
              f"type_converted_to={unit.get('type_converted_to')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
