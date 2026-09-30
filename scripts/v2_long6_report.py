"""Разбор long6: строились ли военные, были ли бои, что выбиралось."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
games, cur, prev = [], [], None
for r in rows:
    t = r.get("ход")
    if prev is not None and t == 1 and isinstance(prev, int) and prev > 1:
        games.append(cur)
        cur = []
    cur.append(r)
    prev = t
games.append(cur)
games = games[-3:]
print("партий:", len(games), "| строк:", [len(g) for g in games])

for i, g in enumerate(games, 1):
    turns = max((r.get("ход") or 0) for r in g)
    ev = [r["нападение"] for r in g if "нападение" in r]
    fights = [r["бой"] for r in g if "бой" in r]
    strike = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "strike")
    esc = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "escape")
    acts = collections.Counter(str((r.get("решение") or {}).get("action")) for r in g)
    warriors = sum(v for k, v in acts.items() if "Warrior" in k or "Phalanx" in k or "Archer" in k)
    print(f"\nпартия {i}: ходов {turns}, решений {len(g)}")
    print(f"  нападений {len(ev)}, боёв {len(fights)}, удар {strike}, выход {esc}")
    print(f"  военных построек: {warriors} | топ действий: {dict(acts.most_common(6))}")
    if fights:
        print("  бои:", json.dumps(fights[:3], ensure_ascii=False))

tail_acts = collections.Counter()
for g in games:
    for r in g:
        a = str((r.get("решение") or {}).get("action"))
        if a.startswith(("produce_", "attack_", "fortify")):
            tail_acts[a] += 1
print("\nвсе постройки/удары/укрепления за 3 партии:", dict(tail_acts.most_common(12)))