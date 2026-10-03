import json

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_s111.jsonl'
engaged = 0
turns_with_disp = 0
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    cands = d.get('кандидаты') or []
    disp = [c for c in cands if 'встаём вплотную' in json.dumps(c, ensure_ascii=False)]
    if not disp:
        continue
    turns_with_disp += 1
    ch = d.get('выбрано') or {}
    ch_actions = {s.get('action') for s in (ch.get('steps') or [])}
    ch_best_variant = None
    for c in cands:
        if c.get('effect') and ch_actions:
            pass
    # лучший вариант среди вытеснения
    disp_actions = set()
    for c in disp:
        lv = c.get('лучший_вариант')
        if lv:
            disp_actions.add(lv)
    if ch_actions & disp_actions:
        engaged += 1

print(f"записей с кандидатом-вытеснением: {turns_with_disp}")
print(f"из них ВЫБРАН вариант-вытеснение: {engaged}")
