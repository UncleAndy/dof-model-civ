"""13.286: решение рабочего стоит за выключенным гейтом; данные для соединения найдены."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.286. Решение рабочего стоит за ВЫКЛЮЧЕННЫМ гейтом — четвёртый раз тот же дефект"
BODY = """## 13.286. Решение рабочего стоит за ВЫКЛЮЧЕННЫМ гейтом — четвёртый раз тот же дефект

При соединении переноса с миром найдено, где именно обязана стоять правка, и найдена ловушка.

### Ловушка (измерено чтением пути)

В `baselines/run_real_tournament.py` решение рабочего вызывается так:

```
if not ARGS.forecast:
    return False, None          # <-- при --no-dof выходим ЗДЕСЬ
...
if getattr(ARGS, "worker_work", True):
    _ww = _flive.worker_work_choice(obs, info, extractor, my_player_id)
```

То есть при `--no-dof` (а именно так меряется приёмка) **решение рабочего не вызывается вовсе**. Это тот же дефект, что я ловил трижды: правило живёт там, где ничего не вызывается (`13.273` — желания в невызываемом `productions()`; `13.280` — то же в пути клина; `13.281` — удержание только в пути клеток города; теперь — решение рабочего). Четвёртый случай, и он крупнее предыдущих: это САМ выбор работы.

Вывод для правки: перенос обязан подключаться на **общий путь** — тот, где действие выбирается при `--no-dof`.

### Данные для соединения — все найдены, изобретать нечего

| что нужно | откуда берём | проверено |
|---|---|---|
| текущие выходы клетки (food/shield/trade) | серверные значения действий города — `env/terrain_output.py: server_tile_outputs` | да |
| выходы ПОСЛЕ работы | приросты из правил мира — `env/terrain_work_effects.py: TERRAIN_WORK_EFFECTS` (`irrigation_food_incr`, `mining_shield_incr`, `road_trade_incr_pct`) | да |
| запаздывание работы (`delay`) | времена из правил террейна: `irrigation_time`, `mining_time`, `cultivate_time`, `plant_time`, `road_time` (`common/terrain.h:215-227` закреплённого коммита) | да, поля подтверждены в его исходнике |
| выбор работы | `brain/ai_default/worker_choice.choose_tile_work` — перенесён (13.284, 13.285) | да, 15 тестов |
| ценность клетки | `brain/ai_default/values.city_tile_value` — перенесён | да |

Соответствие работ остаётся тем, что найдено при переносе: **`plant` = шахта (ACTIVITY_MINE)**, **`cultivate` = орошение (ACTIVITY_IRRIGATE)** (`infracache.c:255-261`).

### Что это меняет в ожиданиях

Раньше я чинил выбор работы счётом совпадений по списку предпочтений и трижды получал «механизм работает, роста нет». Теперь выбор работы — ЕГО формула по ЕГО весам, и правильный вопрос замера меняется: не «появилась ли работа», а «совпал ли выбор работы с тем, что выбрал бы он». Это и надо мерить после соединения.
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
