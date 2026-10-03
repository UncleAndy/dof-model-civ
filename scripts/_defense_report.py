import json, collections, sys

PATH = sys.argv[1] if len(sys.argv) > 1 else \
    '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/city_defense_v2109.jsonl'
rows = [json.loads(l) for l in open(PATH) if l.strip()]

# разбить на партии по сбросу хода
games, cur, prev = [], [], 0
for r in rows:
    if r['ход'] < prev:
        games.append(cur); cur = []
    cur.append(r); prev = r['ход']
if cur:
    games.append(cur)

print(f"партий: {len(games)}, строк: {len(rows)}\n")
tot_lost = tot_lost_noguard = tot_lost_guard = tot_returned = 0
for gi, g in enumerate(games, 1):
    last_turn = max(r['ход'] for r in g)
    cities = collections.OrderedDict()
    for r in g:
        cities.setdefault(r['город'], []).append(r)
    print(f"=== партия {gi}: городов в журнале={len(cities)}, последний ход={last_turn} ===")
    for cid, rs in cities.items():
        turns = [r['ход'] for r in rs]
        guards = [r['защитников_рядом'] for r in rs]
        foes = [r['чужих_рядом'] for r in rs]
        disappeared = turns[-1] < last_turn
        # если город исчезал и потом вернулся — в пределах одного eid не встретится (eid уникален),
        # но проверим наличие разрывов
        tag = ""
        if disappeared:
            tag = "  [исчез до конца]"
            tot_lost += 1
            last = rs[-1]
            if last['защитников_рядом'] > 0:
                tot_lost_guard += 1
            else:
                tot_lost_noguard += 1
            tag += f" в последнем ходу защитников={last['защитников_рядом']}, чужих={last['чужих_рядом']}"
        print(f"  {cid}: ходы {turns[0]}..{turns[-1]} ({len(turns)}), "
              f"защитники max={max(guards)}, чужих max={max(foes)}{tag}")
    print()

print("===== СВОДКА =====")
print(f"городов исчезло до конца партии: {tot_lost}")
print(f"  из них с защитником в последнем ходу: {tot_lost_guard}")
print(f"  из них БЕЗ защитника: {tot_lost_noguard}")
