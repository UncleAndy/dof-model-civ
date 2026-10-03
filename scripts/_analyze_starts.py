import json, math

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_v2109.jsonl'
games = []
cur = []
prev = 0
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    t = d.get('ход', 0)
    if t < prev:
        games.append(cur); cur = []
    cur.append(d); prev = t
if cur:
    games.append(cur)

def coord(d):
    v = d.get('выбрано') or {}
    eff = v.get('effect')
    if isinstance(eff, list) and len(eff) == 3 and eff[0] == 'found_city':
        return (eff[1], eff[2])
    return None

seeds = [9230, 9231, 9232, 9233, 9234]
for gi, g in enumerate(games):
    found = [(d['ход'], coord(d)) for d in g if coord(d)]
    print(f"=== партия {gi+1} (сид {seeds[gi] if gi < len(seeds) else '?'}) ===")
    print(f"  записей={len(g)}, первый ход={g[0]['ход']}, последний={g[-1]['ход']}")
    # первые 3 решения
    for d in g[:3]:
        v = d.get('выбрано') or {}
        r = d.get('решение') or {}
        print(f"    ход {d['ход']}: {r.get('ctrl')}/{r.get('actor')}/{r.get('action')} -> цель {v.get('goal')}")
    print(f"  основания: {found}")
    coords = [c for _, c in found]
    for i in range(len(coords)):
        for j in range(i+1, len(coords)):
            a, b = coords[i], coords[j]
            print(f"    dist({a},{b}) = {math.hypot(a[0]-b[0], a[1]-b[1]):.1f}")
    print()
