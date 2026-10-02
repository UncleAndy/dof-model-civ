import json, math, re
path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_v2108_fix2.jsonl'
found = []
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    v = d.get('выбрано') or {}
    if v.get('goal') != 'found_city':
        continue
    m = re.search(r'в клетке \((\d+),(\d+)\)', v.get('expectation') or '')
    if m:
        found.append((d.get('ход'), int(m.group(1)), int(m.group(2))))

games = []
cur = []
prev = None
for turn, x, y in found:
    if prev is not None and turn < prev:
        games.append(cur); cur = []
    cur.append((turn, x, y)); prev = turn
if cur:
    games.append(cur)

def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)

for gi, g in enumerate(games, 1):
    coords = [(x, y) for _, x, y in g]
    uniq = list(dict.fromkeys(coords))
    ds = [round(dist(uniq[i], uniq[j]), 2) for i in range(len(uniq)) for j in range(i+1, len(uniq))]
    print(f"партия {gi}: оснований={len(g)}, уникальных городов={len(uniq)}")
    print(f"  основания (ход,x,y)={g}")
    if len(uniq) >= 2:
        print(f"  дистанции: {ds}")
    print()