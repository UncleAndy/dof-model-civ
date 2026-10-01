"""Связь вектора `improvements` города с ИМЕНАМИ улучшений.

Мир отдаёт в записи города вектор флагов (`improvements`, длина 68) и, отдельно, в разделе технологий —
`sup_improvements` с полями `id` и `name`. Если индекс вектора = `id`, то имена восстанавливаются, и
появляется возможность мерить вклад улучшения (сравнение «есть / нет»).
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter

data = json.loads(pathlib.Path("tests/fixtures/real_obs_01.json").read_text())
obs = data[0].get("observation") or {}
city = next(iter((obs.get("city") or {}).values()))
vec = city.get("improvements") or []
print(f"вектор improvements: длина {len(vec)}, ненулевых {sum(1 for v in vec if v)}")
print("установленные индексы:", [i for i, v in enumerate(vec) if v])

id2name: dict[int, str] = {}
for tid, t in (obs.get("tech") or {}).items():
    for im in (t.get("sup_improvements") or []):
        if isinstance(im.get("id"), int):
            id2name[im["id"]] = im.get("name") or im.get("rule_name")
print(f"\nимён улучшений из технологий: {len(id2name)} (id {min(id2name)}..{max(id2name)})")
for i in [i for i, v in enumerate(vec) if v]:
    print(f"  индекс {i} → {id2name.get(i, 'НЕ НАЙДЕНО')}")

# проверка гипотезы «индекс = id»: сколько имён вообще попадает в диапазон вектора
in_range = sum(1 for i in id2name if i < len(vec))
print(f"\nимён с id < {len(vec)}: {in_range} из {len(id2name)} — гипотеза «индекс = id» "
      f"{'подтверждается' if in_range > 0.7 * len(id2name) else 'под вопросом'}")
missing = [i for i in range(len(vec)) if i not in id2name]
print(f"индексов без имени: {len(missing)} → {missing[:20]}")