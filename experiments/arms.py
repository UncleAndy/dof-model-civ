#!/usr/bin/env python3
"""Руки абляции политики DOF.

Один раунд — одна карта, все руки играют на одном сиде, DOF-места выбираются
одинаково (`even`: чётные индексы), меняется только НАБОР ПРАВИЛ. Так эффект
приписывается правилу, а не составу мест.

    arms.py --list            # что за руки
    arms.py --spec            # строка для --arms драйвера
    arms.py --check           # сверить пресеты с движком и run_series
"""
import argparse
import re
import sys

# Пресеты должны совпадать с dof_preset_flags() в deploy/freeciv-dof/src/dofpolicy.c
PRESETS = ("full", "ban", "selfdef", "solidarity", "nocoerce", "nowarblock")

ARMS = [
    ("none", "none", "контроль: все места классические"),
    ("ban", "even:ban", "только запрет агрессии (без ответа и солидарности)"),
    ("selfdef", "even:selfdef", "запрет + ответ на нападение на себя"),
    ("solid", "even:solidarity", "предыдущее + война за третьего"),
    ("nowarblock", "even:nowarblock", "полный DOF без блока войны"),
    ("full", "even:full", "полный DOF (поведение прежних серий)"),
]


def spec():
    return ";".join(f"{name}:{policy}" for name, policy, _ in ARMS)


def check():
    """Сверка: пресеты есть в движке (по исходнику) и в run_series."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "deploy", "freeciv-dof", "src", "dofpolicy.c"),
               encoding="utf-8").read()
    known = set(re.findall(r'fc_strcasecmp\(name, "([a-z]+)"\)', src))
    sys.path.insert(0, os.path.join(root, "deploy", "freeciv-dof"))
    import run_series
    ok = True
    for name in PRESETS:
        if name not in known:
            print(f"НЕТ в dofpolicy.c: {name}")
            ok = False
        if name not in run_series.PRESETS:
            print(f"НЕТ в run_series.PRESETS: {name}")
            ok = False
    for name, policy, _ in ARMS:
        base, _, preset = policy.partition(":")
        if preset and preset not in known:
            print(f"рука {name}: пресет {preset} неизвестен движку")
            ok = False
    print("пресеты совпадают" if ok else "РАСХОЖДЕНИЕ")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--spec", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        sys.exit(0 if check() else 1)
    if a.spec:
        print(spec())
        return
    for name, policy, what in ARMS:
        print(f"{name:11} {policy:18} {what}")


if __name__ == "__main__":
    main()
