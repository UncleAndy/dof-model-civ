"""Итог серии def7 (§10.113/§10.114/§10.115) с ФИЛЬТРОМ по НОМЕРУ ПАРТИИ.

В traces_def7.jsonl есть мусор от упавшей попытки (пустая база, партии с 1).
Поле «партия» в трейсе ОТСУТСТВУЕТ — поэтому партия определяется по ресету
счётчика хода на 1. Текущая серия — партии со 2-й (первая — мусор).

Запуск: python scripts/_verdict_def7.py [min_party]
"""
import collections
import json
import sys

MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 2
#: В city_defense_* партии нумеруются сквозным счётчиком (107..114 для этой серии),
#: в traces — ресетом хода (партий 9: №1 мусор). Чтобы оба фильтра совпали,
#: в defense пропускаем партии с номером < MIN_DEF.
MIN_DEF = int(sys.argv[2]) if len(sys.argv) > 2 else 107
TR = "knowledge/traces_def7.jsonl"
RES = "knowledge/results_def7.jsonl"
DEF = "knowledge/city_defense_def7.jsonl"

lines = open(TR, encoding="utf-8").read().splitlines()
turns = []
for l in lines:
    try:
        turns.append(json.loads(l).get("ход"))
    except Exception:
        turns.append(None)
starts = [i for i in range(len(turns)) if turns[i] == 1 and (i == 0 or turns[i - 1] != 1)]
starts.append(len(turns))

goals = collections.Counter()
party_goals = collections.defaultdict(collections.Counter)
attacks = 0
for pi in range(len(starts) - 1):
    party = pi + 1
    if party < MIN:
        continue
    for i in range(starts[pi], starts[pi + 1]):
        try:
            d = json.loads(lines[i])
        except Exception:
            continue
        ch = d.get("выбрано") or {}
        goal = ch.get("goal") or ""
        step0 = (ch.get("steps") or [{}])[0] if ch.get("steps") else {}
        act = step0.get("action") or ""
        goals[goal] += 1
        party_goals[party][goal] += 1
        if act.startswith("attack"):
            attacks += 1

print(f"=== ПОВЕДЕНИЕ (партии >= {MIN}, рабочий трейс) ===")
for g, n in goals.most_common():
    print(f"  {g or '(нет)':12s} {n}")
print(f"  атак (attack) выбрано: {attacks}")

print(f"\n=== ПО ПАРТИЯМ (партии >= {MIN}) ===")
for p in sorted(party_goals):
    g = party_goals[p]
    print(f"  партия {p}: cover={g.get('cover',0)} strike={g.get('strike',0)} "
          f"intercept={g.get('intercept',0)} escape={g.get('escape',0)} "
          f"explore={g.get('explore',0)} found_city={g.get('found_city',0)} "
          f"channel={g.get('channel',0)}")

print("\n=== ИСХОДЫ ПАРТИЙ ===")
try:
    rows = [json.loads(l) for l in open(RES)]
except FileNotFoundError:
    rows = []
surv = 0
for r in rows:
    de = bool(r.get("наблюдение_пустое"))
    surv += 0 if de else 1
    print(f"  сид {r['seed']}: ходов {r['ходов_сыграно']:3d}  счёт {str(r['счёт']):>4}  "
          f"городов {r['городов']}  юнитов {r['юнитов']:3d}  простоев {r['ходов_без_действия']}  "
          f"{'ПОРАЖЕНИЕ' if de else 'выжил'}")
print(f"  ИТОГ: выжил {surv}/{len(rows)}; городов {sum(r['городов'] or 0 for r in rows)}; "
      f"юнитов {sum(r['юнитов'] or 0 for r in rows)}")

print(f"\n=== ПОТЕРИ ГОРОДОВ (defense-партии >= {MIN_DEF}) ===")
seq = collections.defaultdict(dict)
ever = collections.defaultdict(set)
try:
    for line in open(DEF):
        d = json.loads(line)
        p = d.get("партия") or 0
        if p < MIN_DEF:
            continue
        c = d.get("город")
        seq[p][c] = bool(d.get("свой"))
        if d.get("свой"):
            ever[p].add(c)
except FileNotFoundError:
    pass
for p in sorted(seq):
    lost = sum(1 for c in ever[p] if seq[p].get(c) is False)
    print(f"  партия {p}: было своих {len(ever[p])}, потеряно {lost}")
