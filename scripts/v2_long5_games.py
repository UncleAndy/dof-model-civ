"""Разбор последних трёх партий (long5) по отдельности: бои, удар, производство, исход."""
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
print("партий в разборе:", len(games), "| строк:", [len(g) for g in games])

for i, g in enumerate(games, 1):
    turns = max((r.get("ход") or 0) for r in g)
    ev = [r["нападение"] for r in g if "нападение" in r]
    fights = [r["бой"] for r in g if "бой" in r]
    strike = [r for r in g if str((r.get("выбрано") or {}).get("goal")) == "strike"]
    src = sum(1 for r in g if r.get("источники_коллапса"))
    nz = sum(1 for r in g if ((r.get("риск") or {}).get("цена") or 0) > 0)
    esc = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "escape")
    prod = collections.Counter(str((r.get("решение") or {}).get("action")) for r in g
                              if str((r.get("решение") or {}).get("action")).startswith("produce_"))
    print(f"\nпартия {i}: ходов {turns}, решений {len(g)}")
    print(f"  нападений {len(ev)} (атрибутировано {sum(1 for e in ev if e.get('нападающий'))}), "
          f"боёв {len(fights)}, источников {src}, цена>0 {nz}, выход {esc}, удар {len(strike)}")
    print(f"  производство: {dict(prod)}")
    if fights:
        print("  бои:", json.dumps(fights[:3], ensure_ascii=False))