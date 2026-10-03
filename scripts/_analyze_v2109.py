import json, collections
c = collections.Counter()
found = collections.Counter()
prod = collections.Counter()
for line in open('/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_v2109.jsonl'):
    try:
        d = json.loads(line)
    except Exception:
        continue
    v = d.get('выбрано') or {}
    g = v.get('goal', '?')
    c[g] += 1
    if g == 'found_city':
        found[(d.get('ход'), str(v.get('effect')))] += 1
    # ищем постройку в вариантах
    for cand in (d.get('кандидаты') or []):
        eff = cand.get('effect')
        if isinstance(eff, list) and eff and eff[0] in ('build', 'start_build', 'production'):
            prod[str(eff[1])] += 1

print("=== выбрано.goal ===")
for k, n in c.most_common(30):
    print(f"{n:6d}  {k}")
print()
print("=== found_city события (ход, effect) ===")
for k, n in sorted(found.items(), key=lambda x: x[0][0] or 0):
    print(k, n)
print()
print("=== кандидаты-постройки ===")
for k, n in prod.most_common(30):
    print(f"{n:6d}  {k}")
