"""Чем мир помечает НЕраскрытую клетку: terrain, output, status — смотрим распределения."""
import json
from collections import Counter

d = json.load(open("/tmp/v2_late_9000.json"))
m = d["observation"].get("map") or {}
for key in ("terrain", "output", "status", "extras", "tile_owner", "unit_owner"):
    v = m.get(key)
    if v is None:
        print(f"{key}: нет")
        continue
    try:
        flat = [x for col in v for x in (col if isinstance(col, list) else [col])]
    except TypeError:
        flat = [v]
    c = Counter(str(x) for x in flat)
    print(f"{key}: {len(flat)} клеток, значения: {dict(c.most_common(6))}")