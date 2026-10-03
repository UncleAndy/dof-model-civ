import json, re

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_v2109.jsonl'
games = []
cur = {'found': [], 'turns': 0, 'last_turn': 0}
seen_turn = 0
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    t = d.get('ход', 0)
    if t < seen_turn:  # новая партия
        games.append(cur)
        cur = {'found': [], 'turns': 0, 'last_turn': 0}
    seen_turn = t
    cur['turns'] += 1
    cur['last_turn'] = t
    v = d.get('выбрано') or {}
    if v.get('goal') == 'found_city':
        eff = v.get('effect')
        cur['found'].append((t, eff))
if cur['turns']:
    games.append(cur)

for gi, g in enumerate(games, 1):
    print(f"партия {gi}: записей={g['turns']}, последний ход={g['last_turn']}, found_city={len(g['found'])}")
    for t, eff in g['found']:
        print(f"    ход {t}: {eff}")
