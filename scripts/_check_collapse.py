import json, sys, collections
path = sys.argv[1]
src_recs = 0
src_turns = set()
attack_cand = 0
attack_chosen = 0
exp_kinds = collections.Counter()
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    src = d.get('источники_коллапса') or {}
    if src:
        src_recs += 1
        src_turns.add(d.get('ход'))
    for c in (d.get('кандидаты') or []):
        eff = c.get('effect')
        if isinstance(eff, list) and eff and str(eff[0]).startswith('attack'):
            attack_cand += 1
        if 'удар' in str(c.get('почему') or '') or 'ОТПОР' in str(c.get('почему') or ''):
            attack_cand += 0
    ch = d.get('выбрано') or {}
    for s in (ch.get('steps') or []):
        a = s.get('action') or ''
        if a.startswith('attack'):
            attack_chosen += 1
        exp_kinds[a.split('_')[0]] += 1
print(f"записей с непустыми 'источники_коллапса': {src_recs}; ходов: {len(src_turns)}")
print(f"кандидатов с эффектом attack: {attack_cand}; выбрано attack: {attack_chosen}")
print("семейства выбранных:", dict(exp_kinds.most_common(12)))