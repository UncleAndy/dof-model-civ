import json, math, collections, sys

trace = sys.argv[1]
growth = sys.argv[2]
seeds = [int(x) for x in sys.argv[3].split(',')] if len(sys.argv) > 3 else []

# --- трейс: партии, старт, основания ---
rows = []
prev = 0
games = []
cur = []
for line in open(trace):
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
    eff = (d.get('выбрано') or {}).get('effect')
    if isinstance(eff, list) and len(eff) == 3 and eff[0] == 'found_city':
        return (eff[1], eff[2])
    return None

print("========== ТРЕЙС ==========")
for gi, g in enumerate(games):
    seed = seeds[gi] if gi < len(seeds) else '?'
    found = [(d['ход'], coord(d)) for d in g if coord(d)]
    first = g[0] if g else {}
    v0 = first.get('выбрано') or {}
    r0 = first.get('решение') or {}
    print(f"партия {gi+1} (сид {seed}): записей={len(g)}, ходы {first.get('ход')}..{g[-1]['ход'] if g else '?'}")
    print(f"   1-е решение: {r0.get('ctrl')}/{r0.get('actor')}/{r0.get('action')} -> {v0.get('goal')}")
    print(f"   основания: {found}")
    coords = [c for _, c in found]
    for i in range(len(coords)):
        for j in range(i+1, len(coords)):
            a, b = coords[i], coords[j]
            print(f"     dist({a},{b}) = {math.hypot(a[0]-b[0], a[1]-b[1]):.1f}")

# --- рост городов ---
print("\n========== РОСТ ГОРОДОВ ==========")
grows = [json.loads(l) for l in open(growth) if l.strip()]
gg, curg, prevg = [], [], 0
for r in grows:
    if r['ход'] < prevg:
        gg.append(curg); curg = []
    curg.append(r); prevg = r['ход']
if curg:
    gg.append(curg)
for gi, g in enumerate(gg):
    seed = seeds[gi] if gi < len(seeds) else '?'
    last = max(r['ход'] for r in g)
    cities = collections.OrderedDict()
    for r in g:
        cities.setdefault(r['город'], []).append(r['ход'])
    alive = sum(1 for c, ts in cities.items() if ts[-1] >= last - 1)
    print(f"партия {gi+1} (сид {seed}): городов основано={len(cities)}, живы в конце≈{alive}, последний ход={last}")
    for c, ts in cities.items():
        print(f"     {c}: ходы {ts[0]}..{ts[-1]}")
