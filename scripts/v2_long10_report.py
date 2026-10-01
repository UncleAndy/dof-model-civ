"""Разбор длинного прогона с целью explore: траектория индекса, движение, потери.

Вопрос Andy: «уход/исследование неплохо, если не приводит к разрушению (уменьшению DoF)».
Здесь это проверяется числом: как менялся индекс, сколько было движения и что предшествовало потере.
"""
import collections
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_long10.jsonl"
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
print("строк:", len(rows), "| сегментов:", len(games), "| размеры:", [len(g) for g in games])

for i, g in enumerate(games, 1):
    turns = max((r.get("ход") or 0) for r in g)
    idx = [r.get("индекс") for r in g if isinstance(r.get("индекс"), (int, float))]
    acts = collections.Counter(str((r.get("решение") or {}).get("action")) for r in g)
    goals = collections.Counter()
    for r in g:
        ch = r.get("выбрано")
        if isinstance(ch, dict):
            goals[str(ch.get("goal"))] += 1
    ev = [r["нападение"] for r in g if "нападение" in r]
    fights = [r["бой"] for r in g if "бой" in r]
    moves = sum(v for k, v in acts.items() if k.startswith("goto_"))
    print(f"\n=== сегмент {i}: ходов {turns}, решений {len(g)} ===")
    if idx:
        print(f"  индекс: начало {idx[0]:.2f}, максимум {max(idx):.2f}, конец {idx[-1]:.2f}")
    print(f"  движения (goto_*): {moves} ({100 * moves / max(1, len(g)):.1f}%)")
    print(f"  цели: {dict(goals.most_common(5))}")
    print(f"  нападений {len(ev)}, боёв {len(fights)}")
    print(f"  топ действий: {dict(acts.most_common(6))}")
    # что было в последних решениях перед концом
    print("  последние 4 решения:")
    for r in g[-4:]:
        ch = r.get("выбрано") or {}
        print(f"    ход {r.get('ход')}: {str(ch.get('effect'))[:40]} | индекс {r.get('индекс')} | "
              f"источников {(r.get('источники_коллапса') or {}) and len(r.get('источники_коллапса'))}")