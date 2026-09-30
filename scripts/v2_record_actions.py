"""Что агент делает в записываемом прогоне: сколько действий ДВИЖЕНИЯ против прочих."""
import collections
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_record2.jsonl"
rows = [json.loads(line) for line in open(path)]
print("решений:", len(rows))

acts = collections.Counter(str((r.get("решение") or {}).get("action")) for r in rows)
move = {k: v for k, v in acts.items()
        if k.startswith(("goto_", "build_road", "irrigation", "cultivate", "plant", "fortify"))}
print("\nдействия ДВИЖЕНИЯ/работы:", sum(move.values()), "из", sum(acts.values()), 
      f"({100 * sum(move.values()) / max(1, sum(acts.values())):.1f}%)")
for k, v in sorted(move.items(), key=lambda kv: -kv[1])[:10]:
    print(f"   {v:4d}  {k}")

print("\nвсе прочие (топ-10):")
for k, v in acts.most_common(10):
    print(f"   {v:4d}  {k}")

goals = collections.Counter()
for r in rows:
    ch = r.get("выбрано")
    goals[str((ch or {}).get("goal")) if isinstance(ch, dict) else "—"] += 1
print("\nцели выбранных путей:", dict(goals.most_common(8)))

# ходы, где были движения, и сколько их
turns_move = collections.Counter()
for r in rows:
    a = str((r.get("решение") or {}).get("action"))
    if a.startswith("goto_"):
        turns_move[r.get("ход")] += 1
print("\nходов с движением юнита:", len(turns_move), "| примеры:", list(turns_move.items())[:8])