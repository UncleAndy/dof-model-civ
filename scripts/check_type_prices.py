#!/usr/bin/env python
"""Почему тип попадает в «без цены»: опции каталога или стоимость?

Печатает для предложенных типов оба числа по отдельности: опции из каталога
извлекателя (`unit_type_options`) и стоимость из склада замеров.

    python scripts/check_type_prices.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def main() -> int:
    import warnings
    warnings.filterwarnings("ignore")

    from env.entity_extractor import GameStateExtractor, unit_options
    from env.measured_facts import default_facts

    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]

    extractor = GameStateExtractor(my_player_id=0)
    result = extractor.extract(obs, {}, turn=1)
    catalogue = result.state.bridge.unit_type_options
    facts = default_facts()

    interesting = ["Settlers", "Workers", "Warriors", "Explorer", "Engineers", "Phalanx"]
    print(f"{'тип':12s} {'опции каталога':>16s} {'стоимость':>10s}")
    for name in interesting:
        print(f"{name:12s} {catalogue.get(name, '—'):>16} "
              f"{facts.cost(name) if facts.cost(name) is not None else '—':>10}")

    print("\nесть ли в каталоге носители населения:")
    for key, value in sorted(catalogue.items()):
        if "settl" in key.lower() or "engineer" in key.lower():
            print(f"   {key} = {value}")

    print("\nкаталог юнитов, имена на W и B:")
    for key in sorted(catalogue):
        if key[:1] in ("W", "B"):
            print(f"   юнит  {key} = {catalogue[key]}")
    print("каталог улучшений, имена на W и B:")
    for key in sorted(result.state.bridge.improvement_options):
        if key[:1] in ("W", "B"):
            print(f"   улучш {key} = {result.state.bridge.improvement_options[key]}")

    print("\nживые юниты фикстуры — какие поля называют тип:")
    for uid, unit in list((obs.get("unit") or {}).items())[:3]:
        if isinstance(unit, dict):
            named = {k: v for k, v in unit.items()
                     if "type" in k.lower() or "rule" in k.lower() or "name" in k.lower()}
            print(f"   {uid}: {json.dumps(named, default=str)[:220]}")
            spec = {k: v for k, v in unit.items() if k.startswith("type_")}
            if spec:
                print(f"        unit_options(spec) = {unit_options(spec)[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
