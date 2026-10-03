"""Качество прикрытия города: когда рядом чужой — был ли рядом наш ЗАЩИТНИК?

Прямая проверка задачи Andy: «юниты надёжно прикрывали город при наличии чужих юнитов».
Сравниваем старую и новую серии.
"""
import json, sys

def city_cover(path):
    threat_turns = 0
    covered = 0
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not d.get("свой"):
            continue
        foes = d.get("чужих_рядом") or 0
        if foes <= 0:
            continue
        threat_turns += 1
        if (d.get("защитников_рядом") or 0) >= 1:
            covered += 1
    return threat_turns, covered


def incursion_response(path):
    tot = 0
    with_mil = 0
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        tot += 1
        if (d.get("военных_рядом") or 0) >= 1:
            with_mil += 1
    return tot, with_mil


for label, cpath, ipath in [("СТАРАЯ (def)", "knowledge/city_defense_def.jsonl",
                            "knowledge/city_incursion_def.jsonl"),
                            ("НОВАЯ (def4)", "knowledge/city_defense_def4.jsonl",
                             "knowledge/city_incursion_def4.jsonl")]:
    try:
        t, c = city_cover(cpath)
        i, m = incursion_response(ipath)
        print(f"{label}:")
        print(f"  ходов «у нашего города чужой»: {t}; из них с защитником: {c} "
              f"({100.0 * c / t:.1f}%)" if t else f"  {label}: нет данных по городам")
        print(f"  вторжений: {i}; из них при нашем военном рядом: {m} "
              f"({100.0 * m / i:.1f}%)" if i else f"  {label}: нет вторжений")
    except FileNotFoundError as e:
        print(f"{label}: файла нет ({e.filename})")