import json, math, collections, sys

def load_games(path, key='ход'):
    games, cur, prev = [], [], 0
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get(key, 0)
        if t < prev:
            games.append(cur); cur = []
        cur.append(d); prev = t
    if cur:
        games.append(cur)
    return games

def coord(d):
    eff = (d.get('выбрано') or {}).get('effect')
    if isinstance(eff, list) and len(eff) == 3 and eff[0] == 'found_city':
        return (eff[1], eff[2])
    return None

# usage: label trace growth  (triples)
args = sys.argv[1:]
for i in range(0, len(args), 3):
    lab, tr, gr = args[i], args[i+1], args[i+2]
    games = load_games(tr)
    grows = load_games(gr)
    print(f"--- {lab} ---")
    n = max(len(games), len(grows))
    for gi in range(n):
        g = games[gi] if gi < len(games) else []
        grow = grows[gi] if gi < len(grows) else []
        last = g[-1]['ход'] if g else '?'
        found = [(d['ход'], coord(d)) for d in g if coord(d)]
        coords = [c for _, c in found]
        ds = [round(math.hypot(coords[a][0]-coords[b][0], coords[a][1]-coords[b][1]), 1)
              for a in range(len(coords)) for b in range(a+1, len(coords))]
        cs = collections.OrderedDict()
        for r in grow:
            cs.setdefault(r['город'], []).append(r['ход'])
        alive = (max(r['ход'] for r in grow) if grow else 0)
        alive_n = sum(1 for ts in cs.values() if ts[-1] >= alive - 1)
        print(f"  партия {gi+1}: последний ход={last}, оснований={len(found)}, дистанции={ds}")
        print(f"     основания: {found}")
        print(f"     рост: городов_в_журнале={len(cs)}, живы_в_конце≈{alive_n}, последний_ход_журнала={alive}")
