"""Разбор long8 (бой, начатый врагом, как измерение): бои, цена удара, удар, итоги."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces_long8.jsonl")]
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
print("сегментов:", len(games), "| строк:", [len(x) for x in games])

for i, g in enumerate(games, 1):
    turns = max((r.get("ход") or 0) for r in g)
    ev = [r["нападение"] for r in g if "нападение" in r]
    fights = [r["бой"] for r in g if "бой" in r]
    strike = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "strike")
    esc = sum(1 for r in g if str((r.get("выбрано") or {}).get("goal")) == "escape")
    acts = collections.Counter(str((r.get("решение") or {}).get("action")) for r in g)
    mil = sum(v for k, v in acts.items()
              if any(w in k for w in ("Warrior", "Phalanx", "Archer", "Horsemen", "Legion")))
    print(f"\nсегмент {i}: ходов {turns}, решений {len(g)}")
    print(f"  нападений {len(ev)} (атриб. {sum(1 for e in ev if e.get('нападающий'))}), "
          f"боёв {len(fights)}, удар {strike}, выход {esc}, военных построек {mil}")
    print(f"  топ действий: {dict(acts.most_common(6))}")
    if fights:
        for f in fights[:3]:
            print("  бой:", json.dumps(f, ensure_ascii=False))

last = rows[-1].get("бои") if rows else None
print("\nстатистика боёв в конце:", json.dumps(last, ensure_ascii=False))

# были ли попытки удара среди кандидатов и с какой ценой
print("\nкандидаты со семейством attack:")
n = 0
for r in rows:
    for c in (r.get("кандидаты") or []):
        if "attack" in str(c.get("эффект")):
            print(f"  ход {r.get('ход')}: net={c.get('net_delta')} | {str(c.get('почему'))[:120]}")
            n += 1
            break
    if n >= 5:
        break
if n == 0:
    print("  таких кандидатов не было")