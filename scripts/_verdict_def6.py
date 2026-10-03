"""Сводка по серии обороны (§10.113/§10.114): поведение + исходы + потери городов.

Запуск:  python scripts/_verdict_def6.py [traces] [results] [defense]
"""
import json, sys, collections

trace = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_def6.jsonl"
results = sys.argv[2] if len(sys.argv) > 2 else "knowledge/results_def6.jsonl"
deflog = sys.argv[3] if len(sys.argv) > 3 else "knowledge/city_defense_def6.jsonl"

cover_c = cover_e = disp_c = disp_e = def_c = def_e = atk = 0
goals = collections.Counter()
for line in open(trace):
    try:
        d = json.loads(line)
    except Exception:
        continue
    cands = d.get("кандидаты") or []
    ch = (d.get("выбрано") or {})
    ch_act = ((ch.get("steps") or [{}])[0].get("action")) or ""
    ch_goal = ch.get("goal") or ""
    goals[ch_goal] += 1
    if ch_act.startswith("attack"):
        atk += 1
    for c in cands:
        blob = json.dumps(c, ensure_ascii=False)
        act = c.get("лучший_вариант") or c.get("action") or ""
        if "прикрываем" in blob:
            cover_c += 1
            if ch_act and act and ch_act == act:
                cover_e += 1
        elif "встаём вплотную" in blob:
            disp_c += 1
            if ch_act and act and ch_act == act:
                disp_e += 1
        elif "ОТПОР" in blob:
            def_c += 1
            if ch_act and act and ch_act == act:
                def_e += 1

print("=== ПОВЕДЕНИЕ ===")
print(f"  прикрытие : кандидат {cover_c:5d}  выбрано {cover_e:5d}")
print(f"  вытеснение: кандидат {disp_c:5d}  выбрано {disp_e:5d}")
print(f"  ОТПОР     : кандидат {def_c:5d}  выбрано {def_e:5d}")
print(f"  атак (attack) выбрано всего: {atk}")
print(f"  цели выбора: {dict(goals.most_common(8))}")

print()
print("=== ИСХОДЫ ПАРТИЙ ===")
try:
    rows = [json.loads(l) for l in open(results)]
except FileNotFoundError:
    rows = []
if not rows:
    print("  (результатов ещё нет)")
for r in rows:
    defeated = r.get("наблюдение_пустое")
    print(f"  сид {r['seed']}: ходов {r['ходов_сыграно']:3d}  счёт {str(r['счёт']):>4}  "
          f"городов {r['городов']}  юнитов {r['юнитов']:3d}  "
          f"{'ПОРАЖЕНИЕ' if defeated else 'выжил'}  простоев {r['ходов_без_действия']}")
surv = sum(1 for r in rows if not r.get("наблюдение_пустое"))
print(f"  итог: выжил {surv}/{len(rows)}; "
      f"городов всего {sum(r['городов'] or 0 for r in rows)}; "
      f"юнитов всего {sum(r['юнитов'] or 0 for r in rows)}")

print()
print("=== ПОТЕРИ ГОРОДОВ (был наш → стал чужой) ===")
seq = collections.defaultdict(dict)
ever = collections.defaultdict(set)
try:
    for line in open(deflog):
        d = json.loads(line)
        p, c = d.get("партия"), d.get("город")
        seq[p][c] = bool(d.get("свой"))
        if d.get("свой"):
            ever[p].add(c)
except FileNotFoundError:
    pass
for p in sorted(seq):
    lost = sum(1 for c in ever[p] if seq[p].get(c) is False)
    print(f"  партия {p}: своих городов было {len(ever[p])}, потеряно {lost}")
print(f"  ВСЕГО потеряно: {sum(sum(1 for c in ever[p] if seq[p].get(c) is False) for p in seq)}")
