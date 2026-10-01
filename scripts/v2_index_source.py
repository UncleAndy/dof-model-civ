"""Растёт ли индекс за счёт ОБНАРУЖЕННЫХ ЧУЖИХ (мирные плюсуются, §10.33) — проверка числами."""
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

for i, g in enumerate(games, 1):
    print(f"\n=== сегмент {i} ===")
    seen = []
    for r in g:
        f = r.get("чужое") or {}
        if isinstance(f, dict):
            seen.append((r.get("ход"), f.get("юнитов"), f.get("угроз"),
                         round(r.get("индекс") or 0, 2)))
    if not seen:
        print("  поля «чужое» нет")
        continue
    print(f"  чужих в графе: начало {seen[0][1]}, максимум "
          f"{max(x[1] or 0 for x in seen)}, конец {seen[-1][1]}")
    print("  ход / чужих / угроз / индекс (выборка):")
    for x in seen[::max(1, len(seen) // 8)][:9]:
        print(f"    {x[0]:4d} / {x[1]} / {x[2]} / {x[3]}")