"""Сводка по серии §10.113/§10.114: итоги партий + поведение (атаки, прикрытие, отпор, захваты)."""
import json, sys, collections

res = sys.argv[1]
trace = sys.argv[2]
deflog = sys.argv[3] if len(sys.argv) > 3 else None

print("===== ИТОГИ ПАРТИЙ =====")
rows = [json.loads(l) for l in open(res) if l.strip()]
elim = 0
for r in rows:
    dead = (r.get('городов') == 0 and not r.get('счёт'))
    elim += 1 if dead else 0
    print(f"  сид {r['seed']}: ход={r['ходов_сыграно']} счёт={r.get('счёт')} городов={r.get('городов')} "
          f"юнитов={r.get('юнитов')} простоев={r.get('ходов_без_действия')} "
          f"{'УНИЧТОЖЕН' if dead else ''}")
print(f"  → уничтожено: {elim}/{len(rows)}")

att_chosen = cover_eng = cover_cand = def_eng = def_cand = 0
src_turns = set()
for line in open(trace):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get('источники_коллапса'):
        src_turns.add(d.get('ход'))
    ch = d.get('выбрано') or {}
    ca = {s.get('action') for s in (ch.get('steps') or [])}
    for a in ca:
        if a and a.startswith('attack'):
            att_chosen += 1
    cov, dfn = set(), set()
    for c in (d.get('кандидаты') or []):
        blob = json.dumps(c, ensure_ascii=False)
        lv = c.get('лучший_вариант')
        if lv and 'прикрываем' in blob:
            cov.add(lv)
        if lv and 'ОТПОР' in blob:
            dfn.add(lv)
    if cov:
        cover_cand += 1
        cover_eng += 1 if (ca & cov) else 0
    if dfn:
        def_cand += 1
        def_eng += 1 if (ca & dfn) else 0

print("\n===== ПОВЕДЕНИЕ =====")
print(f"  ходов с источниками коллапса: {len(src_turns)}")
print(f"  выбрано attack-действий: {att_chosen}")
print(f"  прикрытие: кандидат в {cover_cand} решениях, выбрано {cover_eng}")
print(f"  отпор:     кандидат в {def_cand} решениях, выбрано {def_eng}")

if deflog:
    import os
    if os.path.exists(deflog):
        rows2 = [json.loads(l) for l in open(deflog) if l.strip()]
        own = collections.defaultdict(set)
        owners = collections.defaultdict(set)
        for r in rows2:
            owners[r['город']].add(r['owner'])
            if r['свой']:
                own[r['город']].add(1)
        captured = [c for c, o in owners.items() if own.get(c) and any(x != 0 for x in o)]
        print(f"\n===== ГОРОДА (смена владельца) =====")
        print(f"  наших городов в журнале: {len(own)}; ЗАХВАЧЕНО противником: {len(captured)}")
        for c in captured:
            print(f"    {c}: owners={sorted(owners[c])}")