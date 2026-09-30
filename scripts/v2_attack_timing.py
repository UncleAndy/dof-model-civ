"""Когда именно зафиксированы «город потерян без нападающего»: середина партии или её конец?

Если событие стоит в самом конце партии, оно может быть артефактом исключения из игры
(мир больше не отдаёт город), а не нападением. Это надо знать, а не предполагать.
"""
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-1200:]

# границы партий: возврат счётчика хода к 1
bounds, prev = [], None
for i, r in enumerate(tail):
    t = r.get("ход")
    if prev is not None and t == 1 and isinstance(prev, int) and prev > 1:
        bounds.append(i)
    prev = t
print("границы партий (индексы в хвосте):", bounds, "всего строк:", len(tail))

for i, r in enumerate(tail):
    ev = r.get("нападение")
    if not ev:
        continue
    # номер партии
    game = sum(1 for b in bounds if i >= b)
    print(f"  партия {game + 1}, индекс {i}, ход {r.get('ход')}: {ev.get('вид')} "
          f"{ev.get('как')} нападающий={ev.get('нападающий')}")

print("\nпоследний ход по партиям:", [tail[b - 1].get("ход") for b in bounds],
      "и в самом конце:", tail[-1].get("ход"))