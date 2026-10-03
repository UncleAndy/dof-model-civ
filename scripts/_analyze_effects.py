import json, collections

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_v2109.jsonl'
keys = ['city_lost', 'city_captured', 'city_new', 'city_grew', 'city_destroyed',
        'город', 'чужой_город', 'city_options_delta', 'city_prod_eta_changed']
c = collections.Counter()
eff_counter = collections.Counter()
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    # effects, добытые агентом
    for k, v in (d.get('эффекты') or {}).items():
        c[k] += 1
    # ищем любые упоминания в эффектах кандидатов
    for cand in (d.get('кандидаты') or []):
        eff = cand.get('effect')
        if isinstance(eff, list) and eff:
            eff_counter[str(eff[0])] += 1
    v = d.get('выбрано') or {}
    if isinstance(v.get('effect'), list) and v['effect']:
        eff_counter['ВЫБРАНО:' + str(v['effect'][0])] += 1

print("=== эффекты (ключи, добытые) ===")
for k, n in c.most_common(60):
    print(f"{n:6d}  {k}")
print()
print("=== эффекты кандидатов/выбранных (первый элемент) ===")
for k, n in eff_counter.most_common(60):
    print(f"{n:6d}  {k}")
