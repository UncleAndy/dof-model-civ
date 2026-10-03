import json, sys, random, collections

INC = sys.argv[1]
TRACE = sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 3
D = int(sys.argv[4]) if len(sys.argv) > 4 else 2
R = int(sys.argv[5]) if len(sys.argv) > 5 else 20    # повторов нападения для контроля
random.seed(20261002)

inc_rows = [json.loads(l) for l in open(INC) if l.strip()]
inc_by_game = collections.defaultdict(list)
for r in inc_rows:
    inc_by_game[r.get('партия')].append(r)

# трейс: партии по сбросу хода + нападения
games = []
cur = {'att': [], 'last': 0, 'first': 0}
prev = 0
for line in open(TRACE):
    try:
        d = json.loads(line)
    except Exception:
        continue
    t = d.get('ход', 0)
    if t < prev:
        games.append(cur); cur = {'att': [], 'last': 0, 'first': 0}
    cur['last'] = max(cur['last'], t)
    if not cur['first']:
        cur['first'] = t
    ev = d.get('нападение')
    if isinstance(ev, dict):
        cur['att'].append({'ход': t, 'x': ev.get('x'), 'y': ev.get('y'),
                           'нападающий': ev.get('нападающий')})
    prev = t
if cur['last']:
    games.append(cur)

game_keys = sorted([k for k in inc_by_game if k is not None])

def cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

def preceded(events, turn, x, y):
    return any(0 <= turn - e['ход'] <= W and cheb((x, y), (e['x'], e['y'])) <= D for e in events)

hit = miss = 0
null_hit = null_tot = 0
for gi, g in enumerate(games):
    key = game_keys[gi] if gi < len(game_keys) else None
    events = inc_by_game.get(key, [])
    last = g['last']
    for a in g['att']:
        if a['x'] is None or not events:
            continue
        if preceded(events, a['ход'], a['x'], a['y']):
            hit += 1
        else:
            miss += 1
        for _ in range(R):
            t2 = random.randint(max(2, g['first'] + W), max(2, last - 1))
            null_tot += 1
            if preceded(events, t2, a['x'], a['y']):
                null_hit += 1

tot = hit + miss
print(f"партий в трейсе={len(games)}, множество партий в журнале={game_keys}")
print(f"вторжений: {len(inc_rows)}; нападений (с координатами): {tot}")
if tot:
    print(f"нападений, которым предшествовало вторжение: {hit}/{tot} = {100*hit/tot:.0f}%")
print(f"КОНТРОЛЬ (тот же город/клетка, случайный ход): {null_hit}/{null_tot}"
      + (f" = {100*null_hit/null_tot:.0f}%" if null_tot else ""))

# вторжения: были ли у нас военные рядом
# доля вторжений, за которыми последовала атака (в окне W, радиус D)
att_all = [a for g in games for a in g['att'] if a['x'] is not None]
inc_with_attack = 0
for r in inc_rows:
    if any(0 <= a['ход'] - r['ход'] <= W and cheb((a['x'], a['y']), (r['x'], r['y'])) <= D
           for a in att_all):
        inc_with_attack += 1
print(f"вторжений, за которыми последовала атака: {inc_with_attack}/{len(inc_rows)}"
      f" = {100*inc_with_attack/max(1,len(inc_rows)):.1f}%")
print(f"  → лифт (доля атак со вторжением / контроль): "
      f"{(hit/max(1,tot))/max(1e-9, null_hit/max(1,null_tot)):.1f}×")

mil = sum(1 for r in inc_rows if (r.get('военных_рядом') or 0) > 0)
gd = sum(1 for r in inc_rows if (r.get('защитников_рядом') or 0) > 0)
print(f"вторжений с нашим военным рядом: {mil}/{len(inc_rows)}; с защитником рядом: {gd}/{len(inc_rows)}")
c = collections.Counter(r.get('owner') for r in inc_rows)
print("владельцы вторгавшихся:", dict(c))
print("близость к городу:", dict(collections.Counter(
    '0-1' if (r.get('ближайший_город_дист') or 99) <= 1 else
    '2-3' if (r.get('ближайший_город_дист') or 99) <= 3 else '4+' for r in inc_rows)))