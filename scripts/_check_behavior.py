import json, sys, collections

path = sys.argv[1]
att_chosen = 0
cover_cand = cover_engaged = 0
def_cand = def_engaged = 0
chosen_fam = collections.Counter()
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    ch = d.get('выбрано') or {}
    steps = ch.get('steps') or []
    chosen_actions = {s.get('action') for s in steps}
    if steps:
        a = steps[0].get('action') or ''
        if a.startswith('attack'):
            att_chosen += 1
        chosen_fam['attack' if a.startswith('attack') else a.split('_')[0]] += 1
    cands = d.get('кандидаты') or []
    cov_variants, def_variants = set(), set()
    for c in cands:
        blob = json.dumps(c, ensure_ascii=False)
        lv = c.get('лучший_вариант')
        if lv:
            if 'прикрываем' in blob:
                cov_variants.add(lv)
            if 'ОТПОР' in blob:
                def_variants.add(lv)
    if cov_variants:
        cover_cand += 1
        if chosen_actions & cov_variants:
            cover_engaged += 1
    if def_variants:
        def_cand += 1
        if chosen_actions & def_variants:
            def_engaged += 1
print(f"выбрано attack-действий: {att_chosen}")
print(f"кандидат 'прикрытие': записей {cover_cand}, выбрано {cover_engaged}")
print(f"кандидат 'ОТПОР': записей {def_cand}, выбрано {def_engaged}")
print("выбранные семейства:", dict(chosen_fam.most_common(12)))