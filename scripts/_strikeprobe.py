import json, sys
path = sys.argv[1]
for l in open(path):
    try:
        d = json.loads(l)
    except Exception:
        continue
    if 'нападение' in d or 'бой' in d:
        print(json.dumps({k: d[k] for k in ('ход', 'нападение', 'бой') if k in d},
                         ensure_ascii=False)[:400])
    cands = d.get('кандидаты') or []
    for c in cands:
        blob = json.dumps(c, ensure_ascii=False)
        if 'ОТПОР' in blob or 'удар' in blob:
            print(f"ход {d.get('ход')}: кандидат удар net={c.get('net_delta')} "
                  f"почему={str(c.get('почему'))[:160]}")
            break
