#!/usr/bin/env python
"""Все имена каталога типов: нет ли там Settlers/Warriors в другом написании?

Провод предлагает действия с именами вида `produce_Settlers`, а каталог извлекателя
ключуется по именам спецификаций. Если написание расходится (единственное/множественное
число), цена типа не находится — и это правило сопоставления, а не модель.

    python scripts/check_catalogue_names.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
    sys.path.insert(0, HERE)
    from env.entity_extractor import GameStateExtractor

    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]
    extractor = GameStateExtractor()
    result = extractor.extract(obs, {}, 1)
    bridge = result.state.bridge
    units = sorted(bridge.unit_type_options)
    improve = sorted(bridge.improvement_options)

    print(f"юнитов в каталоге: {len(units)}")
    print("полный список юнитов:")
    for name in units:
        print(f"   {name} = {bridge.unit_type_options[name]:.3f}")
    print(f"\nулучшений в каталоге: {len(improve)}")

    needles = ("settl", "warrior", "worker", "explor", "phalanx", "horseman")
    print("\nпохожие имена среди юнитов:")
    for name in units:
        for needle in needles:
            if needle in name.lower():
                print(f"   {name} = {bridge.unit_type_options[name]:.3f}")
                break
    print("\nпохожие имена среди улучшений:")
    for name in improve:
        for needle in needles + ("barrack",):
            if needle in name.lower():
                print(f"   {name} = {bridge.improvement_options[name]:.3f}")
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
