import json, collections

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/city_growth_v2109.jsonl'
rows = [json.loads(l) for l in open(path) if l.strip()]
# разбить по партиям (ход сбрасывается)
games = []
cur = []
prev = 0
for r in rows:
    if r['ход'] < prev:
        games.append(cur); cur = []
    cur.append(r); prev = r['ход']
if cur:
    games.append(cur)

for gi, g in enumerate(games, 1):
    cities = collections.OrderedDict()
    for r in g:
        c = r['город']
        if c not in cities:
            cities[c] = r['ход']
    print(f"партия {gi}: строк={len(g)}, городов={len(cities)}")
    for c, t in cities.items():
        sizes = [r['размер'] for r in g if r['город'] == c]
        print(f"    {c}: впервые ход {t}, размеры {min(sizes)}..{max(sizes)}, записей {len(sizes)}")
