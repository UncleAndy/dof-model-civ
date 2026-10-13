"""13.284: перенос начат — city_tile_value и уточнение что такое plant и cultivate."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.284. Перенос начат: `city_tile_value` перенесён; `plant` — это ШАХТА, `cultivate` — орошение"
BODY = """## 13.284. Перенос начат: `city_tile_value` перенесён; `plant` — это ШАХТА, `cultivate` — орошение

По указанию владельца («всё, что можно перенести напрямую — переноси») начат буквальный перенос выбора работы.

### Перенесено

`city_tile_value` — `server/advisors/infracache.c:293`, в `brain/ai_default/values.py`, строка в строку:

```
value = food*FOOD_WEIGHTING   + (food>0   ? FOOD_WEIGHTING/2   : 0)
      + shield*SHIELD_WEIGHTING + (shield>0 ? SHIELD_WEIGHTING/2 : 0)
      + trade*TRADE_WEIGHTING   + (trade>0  ? TRADE_WEIGHTING/2  : 0)
```

Веса `advbuilding.h:19-21` (30/17/18) совпадают с нашими `env/config.py:380-382` до цифры. FIXME исходника («foodneed and prodneed are always 0») сохранён как факт: аргументов под них нет, иначе мы повторяли бы несуществующее поведение.

Охрана: `tests/unit/test_ai_default_city_tile_value.py` (5 тестов). Один из них — **сторож на сам источник**: он читает `infracache.c` в `drafts/reference/freeciv-src/` и требует, чтобы формула там осталась той же. Если источник разошёлся с копией — копия под подозрением.

### Найдено при переносе и важно для дальнейшего

Кэш ценности по работе заполняется так (`infracache.c:255-261`):

```
adv_city_worker_act_set(pcity, cindex, ACTIVITY_MINE,     adv_calc_plant(pcity, ptile));
adv_city_worker_act_set(pcity, cindex, ACTIVITY_IRRIGATE, adv_calc_cultivate(pcity, ptile));
adv_city_worker_act_set(pcity, cindex, ACTIVITY_TRANSFORM, adv_calc_transform(pcity, ptile));
```

То есть в этой версии стенда:

* **`plant` — это ШАХТА.** `adv_calc_plant` считает ценность клетки после перехода `terrain->plant_result`, и её собственный комментарий говорит прямо: «**Mining** would change the terrain type, clearing conflicting extras in the process».
* **`cultivate` — это ОРОШЕНИЕ** (переход `terrain->cultivate_result`).

Значит оценка работы у него — это ценность клетки **после перехода рельефа**, а не «плюс щит к той же клетке». Переходы рельефа у нас уже собранas на предыдущем этапе (`env/terrain_work_effects.py`), поэтому оценка переносится без изобретения.

Отдельно к сведению: наш клин (`13.274`) режет `unit/plant` как безнадёжное (26 отказов, 0 успехов — измерено). Это НЕ отменяется, но теперь видно, что вместе с `plant` мы режем ШАХТУ — самую «дорогую» для города работу по весам (щиты 17 против еды 30). Это гипотеза о возможной потере, а не вывод: проверяется замером после переноса выбора.

### Что осталось перенести (следующий шаг)

`consider_settler_action` (`autoworkers.c:308`) и обход клеток из `settler_evaluate_improvements` (там же, стр. 439, 468-579): пройти каждую клетку радиуса города, взять `oldv = city_tile_value(...)`, для каждой работы взять ценность после перехода, сравнить с учётом `in_use` и `amortize(total, delay)`, при `WORKER_FACTOR = 1024` (`autoworkers.c:70`), причём работа с нулевой выгодой (`best_newv = 0`) не выбирается никогда.
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
