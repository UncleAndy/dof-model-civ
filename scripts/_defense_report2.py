import json, collections, sys

PATH = sys.argv[1]
OWN = int(sys.argv[2]) if len(sys.argv) > 2 else None
rows = [json.loads(l) for l in open(PATH) if l.strip()]
print(f"строк: {len(rows)}")
if not rows:
    raise SystemExit(0)
games = collections.OrderedDict()
for r in rows:
    games.setdefault(r.get('партия'), []).append(r)
print(f"партий (по метке): {len(games)}\n")

for g, rs in games.items():
    last = max(r['ход'] for r in rs)
    cities = collections.OrderedDict()
    for r in rs:
        cities.setdefault(r['город'], []).append(r)
    own_cities = {c: v for c, v in cities.items() if any(x['свой'] for x in v)}
    print(f"=== партия {g}: городов в obs={len(cities)}, из них свои={len(own_cities)}, последний ход={last} ===")
    for c, v in cities.items():
        owners = sorted({x['owner'] for x in v})
        turns = [x['ход'] for x in v]
        guards = [x['защитников_рядом'] for x in v]
        foes = [x['чужих_рядом'] for x in v]
        own_turns = [x['ход'] for x in v if x['свой']]
        verdict = ""
        if own_turns and any(not x['свой'] for x in v):
            verdict = "  ← ЗАХВАЧЕН (был свой, стал чужой)"
        elif own_turns and len(own_turns) < len(turns):
            verdict = "  (свой частично)"
        elif own_turns and turns[-1] < last:
            verdict = "  ← свой, пропал из obs до конца (невидимость/потеря)"
        tag = f" owners={owners} ходы {turns[0]}..{turns[-1]} защитники max={max(guards)} чужих max={max(foes)}"
        if own_turns:
            tag += f" свои_ходы {own_turns[0]}..{own_turns[-1]}"
        print(f"  {c}{tag}{verdict}")
    print()
