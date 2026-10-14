"""13.337: где живёт его оценка строек (план переноса) — наш improvement_value усечён до Output_Bonus."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.337."
BODY = """## 13.337. Его оценка строек: функция названа; наш порт усечён до `Output_Bonus`

После §13.336 узкое место — **цена предмета**: город держит начатое, но подсунуть ему
нужное мы не можем, потому что у нас нет цены. Разбором найден весь путь его оценки строек —
переносить надо его, а не изобретать веса:

| что | где | роль |
|---|---|---|
| `building_advisor_choose` | `server/advisors/advbuilding.c:273` | берёт максимум по `building_want[]`, среди `can_city_build_improvement_now` |
| `building_advisor` → `CALL_FUNC_EACH_AI(build_adv_init/adjust)` | `advbuilding.c:180` | зовёт ИИ-шную набивку желаний |
| `dai_build_adv_adjust` | `ai/default/daicity.c:1941` | пересчёт желаний по городам, «не каждый ход» (`city_data->building_turn`) |
| **`adjust_improvement_wants_by_effects`** | `ai/default/daicity.c:1573` | **ядро**: эффекты здания × `amortize` × число ходов, `is_convert` отдельной ветвью |
| `dai_city_want` | `ai/default/daicity.c:1421/1496` | «ценность города», используется как база |

Наш `brain/ai_default/effects.py:improvement_value` считает **только** `Output_Bonus`, поэтому
измеренные (§13.327) значения — `Library 43.2`, `Marketplace 18.0`, `Barracks 8.0`, а
**`Granary`, `City Walls`, `Coinage`, `Harbor` — ровно `0.0`**. Между тем житница (`Granary`,
`Shrink_Food`) — прямой рычаг того самого роста, который по составу §13.333 отстаёт в 48 раз.
Следствие: даже когда «держать» стало правильным (§13.336), выбирать нам по-прежнему не из чего —
самый полезный для роста предмет оценён нулём и отбрасывается как «не оценённый».

### Следующий шаг (без вариантов)

Перенести `adjust_improvement_wants_by_effects` (`daicity.c:1573`) целиком: ветка `is_convert`,
перебор эффектов с их весами и `amortize(turns)`, где `turns` — ходы до постройки. Пока это не
сделано, «выбор предмета» у нас — выбор из трёх зданий с эффектом выхода и поселенца, который
при размере 1 запрещён его же правилом (`daicity.c:788`).
"""

text = CAL.read_text(encoding="utf-8")
if TITLE in text:
    start = text.find(TITLE)
    end = text.find("\n## 13.", start + len(TITLE))
    text = (text[:start] + BODY.rstrip() + text[end:]) if end >= 0 else (text[:start] + BODY)
    print(f"Replaced {TITLE}")
else:
    text = text.rstrip() + "\n\n" + BODY
    print(f"Appended {TITLE}")
CAL.write_text(text, encoding="utf-8")
