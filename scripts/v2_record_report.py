"""Разбор записанных партий: траектория индекса, нападения, выходы, бои."""
import collections
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_record5.jsonl"
rows = [json.loads(line) for line in open(path)]
games, cur, prev = [], [], None
for r in rows:
    t = r.get("ход")
    if prev is not None and t == 1 and isinstance(prev, int) and prev > 1:
        games.append(cur)
        cur = []
    cur.append(r)
    prev = t
games.append(cur)
print("сегментов:", len(games), "| строк:", [len(g) for g in games])

for i, g in enumerate(games, 1):
    turns = max((r.get("ход") or 0) for r in g)
    idx = [r.get("индекс") for r in g if isinstance(r.get("индекс"), (int, float))]
    ev = [r["нападение"] for r in g if "нападение" in r]
    fights = [r["бой"] for r in g if "бой" in r]
    goals = collections.Counter()
    for r in g:
        ch = r.get("выбрано")
        if isinstance(ch, dict):
            goals[str(ch.get("goal"))] += 1
    src = [r for r in g if r.get("источники_коллапса")]
    nz = [r for r in g if ((r.get("риск") or {}).get("цена") or 0) > 0]
    print(f"\n=== партия {i}: ходов {turns}, решений {len(g)} ===")
    if idx:
        print(f"  индекс: {idx[0]:.2f} → {max(idx):.2f} (макс) → {idx[-1]:.2f} (конец)")
    print(f"  цели: {dict(goals.most_common(4))}")
    print(f"  нападений {len(ev)} (атриб. {sum(1 for e in ev if e.get('нападающий'))}), "
          f"боёв {len(fights)}, решений с источником {len(src)}, с ценой риска {len(nz)}")
    for e in ev[:3]:
        print("   нападение:", json.dumps(e, ensure_ascii=False)[:150])