"""Разбор long7 (с ценой незнания): итоги, бои, удар, сроки, переключения производства."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces_long7.jsonl")]
print("строк:", len(rows))
games, cur, prev = [], [], None
for r in rows:
    t = r.get("ход")
    if prev is not None and t == 1 and isinstance(prev, int) and prev > 1:
        games.append(cur)
        cur = []
    cur.append(r)
    prev = t
games.append(cur)
print("сегментов:", len(games), "| строк по сегментам:", [len(x) for x in games])

for i, g in enumerate(games, 1):
    turns = max((r.get("ход") or 0) for r in g)
    ev = [r["нападение"] for r in g if "нападение" in r]
    fights = [r["бой"] for r in g if "бой" in r]
    strike = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "strike")
    esc = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "escape")
    probe = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "probe")
    acts = collections.Counter(str((r.get("решение") or {}).get("action")) for r in g)
    print(f"\nсегмент {i}: ходов {turns}, решений {len(g)}")
    print(f"  нападений {len(ev)} (атриб. {sum(1 for e in ev if e.get('нападающий'))}), "
          f"боёв {len(fights)}, удар {strike}, выход {esc}, проба {probe}")
    print(f"  топ действий: {dict(acts.most_common(8))}")
    if fights:
        print("  бои:", json.dumps(fights[:4], ensure_ascii=False))

last = rows[-1].get("бои") if rows else None
print("\nстатистика боёв в последнем решении:", json.dumps(last, ensure_ascii=False))
print("записей 'замер_срока':", sum(1 for r in rows if "замер_срока" in r))