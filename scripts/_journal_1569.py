"""13.269: знание о работах — из правил, а не из отозванного нуля."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.269. Знание о работах берётся из правил, а не из отозванного нуля"
BODY = """## 13.269. Знание о работах берётся из правил, а не из отозванного нуля

Отзыв слепых нулей `map.output` (§13.268) вскрыл рассогласование в `action_known`: экстра `Road` считалась известной по старому нулю из `MEASURED_EXTRA_EFFECTS`, а действие `build_road` — нет, потому что его там не было. Полный набор показал это честно: **737 passed, 2 failed**.

Причина не в тестах, а в том, что знание держалось на отозванном нуле. По решению владельца эффект — характеристика мира, и знать его достаточно один раз из кода; поэтому добавлен четвёртый источник знания — правила мира:

* `env/terrain_work_effects.effect_known_from_rules(extra)`: дорога и её виды — из секции `ROAD_EFFECTS` (`road_*`), ирригация и шахта — из полей террейна `TERRAIN_WORK_EFFECTS` (`irrigation_food_incr`, `mining_shield_incr`). Записи правила нет — эффект неизвестен, и это честный ответ, а не ноль.
* `env/experiments.action_known` вызывает его после проверки `MEASURED_EXTRA_EFFECTS`.
* Тест-охранник `test_terrain_work_knowledge_comes_from_rules_not_blind_zero` закрепляет происхождение: `Road` и `Irrigation` ОТСУТСТВУЮТ в `MEASURED_EXTRA_EFFECTS`, но всё равно известны. Прежние два теста исправлены не ослаблением, а сменой посылки: причина знания изменилась, утверждения остались.

Таблица `env/dof_deltas.MEASURED_ACTION_DELTAS` НЕ менялась: её нули — это ΔDoF-индекс (индекс за ход не двигается), отдельная величина, и она остаётся калибровкой моста.

Проверка: целевой набор — **68 passed**; полный набор — **740 passed, 1 xfailed** за 272.19 s (было 737 passed, 2 failed). Коммиты этапа: `0270757` (датчики), `539bb72` (worker_want/founder_want), `51ff6fb` (клин + журнал), `449c98d` (источник знания).

Это проверки кода. Турнирная серия против встроенного `normal` с `--no-dof` не запускалась; parity не оценена.
"""

text = CAL.read_text(encoding="utf-8")
start = text.find(TITLE)
if start >= 0:
    end = text.find("\n## 13.", start + len(TITLE))
    text = text[:start] + BODY.rstrip() + text[end:] if end >= 0 else text[:start] + BODY
else:
    text = text.rstrip() + "\n\n" + BODY
CAL.write_text(text, encoding="utf-8")
print(f"Recorded {TITLE}")
