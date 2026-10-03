"""Баланс «бежать vs прикрывать»: когда у юнита были оба мотива, что он выбрал."""
import json, sys, collections
path = sys.argv[1]
both = 0
chose_cover = 0
chose_escape = 0
cover_only = esc_only = 0
detail = []
for l in open(path):
    try:
        d = json.loads(l)
    except Exception:
        continue
    cands = d.get('кандидаты') or []
    cov = set(); esc = set()
    for c in cands:
        blob = json.dumps(c, ensure_ascii=False)
        lv = c.get('лучший_вариант')
        if not lv:
            continue
        if 'прикрываем' in blob:
            cov.add(lv)
        if 'выходим из-под удара' in blob:
            esc.add(lv)
    ch = {s.get('action') for s in ((d.get('выбрано') or {}).get('steps') or [])}
    goal = (d.get('выбрано') or {}).get('goal')
    if cov and esc:
        both += 1
        if ch & cov and not (ch & esc):
            chose_cover += 1
        elif ch & esc and not (ch & cov):
            chose_escape += 1
        if len(detail) < 6:
            detail.append((d.get('ход'), goal, sorted(ch), sorted(cov), sorted(esc)))
    elif cov:
        cover_only += 1
    elif esc:
        esc_only += 1
print(f"решений с обоими мотивами (прикрыть И бежать): {both}")
print(f"  из них выбрано ПРИКРЫТИЕ: {chose_cover}")
print(f"  из них выбрано БЕГСТВО:   {chose_escape}")
print(f"только прикрытие: {cover_only}; только бегство: {esc_only}")
for t, g, ch, cov, esc in detail:
    print(f"  ход {t}: цель={g} выбрано={ch} cover={cov} escape={esc}")