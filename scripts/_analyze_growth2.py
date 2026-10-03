import json, collections

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/city_growth_v2109.jsonl'
rows = [json.loads(l) for l in open(path) if l.strip()]
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
        cities.setdefault(r['город'], []).append(r['ход'])
    print(f"партия {gi}: городов={len(cities)}, последний ход в партии={g[-1]['ход']}")
    for c, turns in cities.items():
        gaps = sum(1 for i in range(1, len(turns)) if turns[i] - turns[i-1] > 1)
        print(f"    {c}: ходы {turns[0]}..{turns[-1]}, записей {len(turns)}, разрывов {gaps}")
