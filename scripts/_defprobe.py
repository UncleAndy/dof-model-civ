import json, sys
path = sys.argv[1]
shown = 0
for l in open(path):
    try:
        d = json.loads(l)
    except Exception:
        continue
    cands = d.get('кандидаты') or []
    dfn = [c for c in cands if 'ОТПОР' in json.dumps(c, ensure_ascii=False)]
    if not dfn:
        continue
    ch = d.get('выбрано') or {}
    chact = [s.get('action') for s in (ch.get('steps') or [])]
    # лучший выбранный кандидат (совпадающий с выбранным действием)
    best_other = max((c.get('net_delta') or -9e9) for c in cands
                     if c.get('лучший_вариант') not in (None,) and
                     c.get('лучший_вариант') not in (dfn[0].get('лучший_вариант'),))
    print(f"ход {d.get('ход')}: выбрано={chact} цель={ch.get('goal')}")
    for c in dfn[:2]:
        print(f"    ОТПОР-кандидат: лучший={c.get('лучший_вариант')} net={c.get('net_delta')} "
              f"почему={str(c.get('почему'))[:150]}")
    print(f"    лучший NetDelta среди прочих кандидатов≈{best_other:.3f}")
    shown += 1
    if shown >= 5:
        break