import json, math, re
path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_v2108.jsonl'
found = []   # (ход, город_назв_или_-, x, y)
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    v = d.get('выбрано') or {}
    if v.get('goal') != 'found_city':
        continue
    exp = v.get('expectation') or ''
    m = re.search(r'в клетке \((\d+),(\d+)\)', exp)
    if not m:
        continue
    x, y = int(m.group(1)), int(m.group(2))
    found.append((d.get('ход'), x, y))

# раздел партий: ход сбрасывается (след. ход < пред.)
games = []
cur = []
prev = None
for turn, x, y in found:
    if prev is not None and turn < prev:
        games.append(cur)
        cur = []
    cur.append((turn, x, y))
    prev = turn
if cur:
    games.append(cur)

def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)

for gi, g in enumerate(games, 1):
    coords = [(x, y) for _, x, y in g]
    # уникальные города (поселенец может основать и «стоять в клетке»; уникализируем координаты)
    uniq = list(dict.fromkeys(coords))
    ds = []
    for i in range(len(uniq)):
        for j in range(i+1, len(uniq)):
            ds.append(round(dist(uniq[i], uniq[j]), 2))
    print(f"партия {gi}: основания (ход,x,y)={g}")
    if len(uniq) >= 2:
        print(f"  координаты городов: {uniq}, попарные дистанции: {ds}")
    print()