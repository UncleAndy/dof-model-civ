"""Полный замер поведения защиты: прикрытие/отпор/вытеснение + исход партии.
Показывает, СКОЛЬКО раз механика была кандидатом и сколько раз ВЫБРАНА,
а также фактическую геометрию (где стояли наши военные относительно города)."""
import json, sys, collections

path = sys.argv[1]
recs = []
for l in open(path):
    try:
        recs.append(json.loads(l))
    except Exception:
        pass

def chosen_actions(d):
    return {s.get('action') for s in ((d.get('выбрано') or {}).get('steps') or [])}

cover_c = cover_e = disp_c = disp_e = def_c = def_e = 0
attack_chosen = 0
goals = collections.Counter()
for d in recs:
    ch = chosen_actions(d)
    for a in ch:
        if a and a.startswith('attack'):
            attack_chosen += 1
        if a:
            goals[a.split('_')[0]] += 1
    gv = (d.get('выбрано') or {}).get('goal')
    if gv:
        goals['G:' + gv] += 1
    cov = set(); dsp = set(); dfn = set()
    for c in (d.get('кандидаты') or []):
        blob = json.dumps(c, ensure_ascii=False)
        lv = c.get('лучший_вариант')
        if not lv:
            continue
        if 'прикрываем' in blob:
            cov.add(lv)
        if 'вытесняем нарушителя' in blob:
            dsp.add(lv)
        if 'ОТПОР' in blob:
            dfn.add(lv)
    if cov:
        cover_c += 1; cover_e += 1 if (ch & cov) else 0
    if dsp:
        disp_c += 1; disp_e += 1 if (ch & dsp) else 0
    if dfn:
        def_c += 1; def_e += 1 if (ch & dfn) else 0

print(f"записей: {len(recs)}")
print(f"ПРИКРЫТИЕ  : кандидат {cover_c:4d}  выбрано {cover_e:4d}")
print(f"ВЫТЕСНЕНИЕ : кандидат {disp_c:4d}  выбрано {disp_e:4d}")
print(f"ОТПОР      : кандидат {def_c:4d}  выбрано {def_e:4d}")
print(f"attack выбрано всего: {attack_chosen}")
print("goals:", dict(goals.most_common(14)))
