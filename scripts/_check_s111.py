import json, collections

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_s111.jsonl'
pot_recs = 0
pot_src = 0
pot_turns = collections.Counter()
displace = 0
displace_examples = []
pot_price_vals = []
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    p = d.get('потенциальные')
    if isinstance(p, dict):
        n = p.get('источников') or 0
        if n > 0:
            pot_recs += 1
            pot_src += n
            pot_turns[d.get('ход')] += n
            if isinstance(p.get('цена'), (int, float)):
                pot_price_vals.append(p['цена'])
    # решения вытеснения
    ch = d.get('выбрано') or {}
    steps = ch.get('steps') or []
    blob = json.dumps(ch, ensure_ascii=False)
    if 'встаём вплотную' in blob:
        displace += 1
        if len(displace_examples) < 4:
            displace_examples.append((d.get('ход'), ch.get('goal'), ch.get('expectation') or blob[:200]))

print(f"решений с 'потенциальные.источников > 0': {pot_recs}, суммарно источников: {pot_src}")
print(f"ходов с вторжением: {len(pot_turns)}; первые ходы: {sorted(pot_turns)[:10]}")
if pot_price_vals:
    print(f"цена потенциала: min={min(pot_price_vals):.2f} max={max(pot_price_vals):.2f}"
          f" медиана≈{sorted(pot_price_vals)[len(pot_price_vals)//2]:.2f}")
print(f"\nрешений 'встать вплотную к нарушителю': {displace}")
for t, g, e in displace_examples:
    print(f"  ход {t}: цель={g}; {e}")
