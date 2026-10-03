"""Итог серии def7 (§10.113/§10.114/§10.115) с ФИЛЬТРОМ по номеру партии.

В traces_def7.jsonl есть мусор от упавшей попытки (пустая база, партии с 1).
Текущая серия — партии >= MIN_PARTY. Запуск: python scripts/_verdict_def7.py [min_party]
"""
import json, sys, collections

MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 107
TR = "knowledge/traces_def7.jsonl"
RES = "knowledge/results_def7.jsonl"
DEF = "knowledge/city_defense_def7.jsonl"

goals = collections.Counter()
attacks = 0
party_goals = collections.defaultdict(collections.Counter)
for line in open(TR):
    try:
        d = json.loads(line)
    except Exception:
        continue
    p = d.get("партия") or 0
    if p < MIN:
        continue
    ch = d.get("выбрано") or {}
    goal = ch.get("goal") or ""
    act = ((ch.get("steps") or [{}])[0].get("action")) or ""
    goals[goal] += 1
    party_goals[p][goal] += 1
    if act.startswith("attack"):
        attacks += 1

print(f"=== ПОВЕДЕНИЕ (партии >= {MIN}) ===")
for g, n in goals.most_common():
    print(f"  {g or '(нет)':12s} {n}")
print(f"  атак (attack) выбрано: {attacks}")

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

print("\n=== ПОТЕРИ ГОРОДОВ (партии >= {}) ===".format(MIN))
seq = collections.defaultdict(dict)
ever = collections.defaultdict(set)
try:
    for line in open(DEF):
        d = json.loads(line)
        p = d.get("партия") or 0
        if p < MIN:
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
