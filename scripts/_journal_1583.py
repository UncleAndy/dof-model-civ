"""13.283: исходники встроенного ИИ получены локально — перенос стал буквальным."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.283. Исходники встроенного ИИ получены локально — перенос стал буквальным"
BODY = """## 13.283. Исходники встроенного ИИ получены локально — перенос стал буквальным

**Замечание владельца (справедливое):** «всё, что можно перенести из кода встроенного ИИ напрямую в логику нашего агента — так и переноси; тесты и варианты только там, где прямой перенос невозможен».

Разбор показал, что перенос не просто возможен — он уже частично сделан, а я в последних правках (13.275–13.282) чинил СВОИ механизмы вместо того, чтобы копировать его решение. Это была ошибка выбора работы, а не препятствие.

### Препятствие, которое действительно было, и как оно снято

Исходников встроенного ИИ в стенде НЕТ: в контейнере только собранный сервер (`/docker/freeciv/build/`), а `dl_freeciv_default.sh` тянет исходник из `https://github.com/freeciv/freeciv.git` на закреплённый коммит. Коммит найден: **`14b7a645a74155d4f3dd300221c5b4f0ffca8fe8`** (`/docker/freeciv/version.txt`, `FCREV=`).

Исходник получен целиком и лежит локально: **`drafts/reference/freeciv-src/`** (376 МБ, исключён из git записью в `.gitignore`). Теперь любой перенос — буквальная сверка с кодом, а не цитата по памяти.

### Что уже перенесено буквально (`brain/ai_default/`)

Слой переноса существует и работает. В нём: `tile_sum`, `amortize`, `food_starvation`, `shield_starvation`, `site_total`, `settler_want` — то есть логика оценки площадки из `ai/default/daisettler.c` (`cityresult`, `food_starvation` там же, стр. 558).

Сверено значение, которое я раньше считал «параметром модели»: `amortize(benefit, delay) = benefit * pow(1 − 1/MORT, delay)`, где **`MORT = 24`** (`server/advisors/advtools.h:19`), а `amortize` — `server/advisors/advtools.c:29`. То есть дисконт, который виден в наших замерах (`Barracks 3.71 за 30 ход.`), — это ЕГО формула, а не наш параметр: `γ = 1 − 1/24 ≈ 0.9583`. Настраивать тут нечего, надо сверять.

### Чего НЕ хватает — и это ровно то, из-за чего город не растёт

1. **`city_tile_value(pcity, ptile, foodneed, prodneed)`** — `server/advisors/infracache.c:293`. Переносится буквально, 12 строк:

```
value = food*FOOD_WEIGHTING   + (food>0   ? FOOD_WEIGHTING/2   : 0)
      + shield*SHIELD_WEIGHTING + (shield>0 ? SHIELD_WEIGHTING/2 : 0)
      + trade*TRADE_WEIGHTING   + (trade>0  ? TRADE_WEIGHTING/2  : 0)
```

Веса уже есть у нас (`env/config.py`: `AI_FOOD_WEIGHTING = 30.0`, щиты 17, торговля 18 — из его же кода).

2. **Выбор работы рабочим: `settler_evaluate_improvements`** (`server/advisors/autoworkers.c:439`) и **`consider_settler_action`** (там же, стр. 308). Его логика буквально:

   - проходит по КАЖДОЙ клетке в радиусе города (не только под юнитом);
   - `oldv = city_tile_value(pcity, ptile, 0, 0)`;
   - для каждой возможной работы (`aw_transform_action_iterate`) считает новую ценность клетки;
   - сравнивает с учётом `in_use` (клетка уже обрабатывается городом или нет) и запаздывания: `total = (new − old)*WORKER_FACTOR` (или `/2`, если клетка не обрабатывается) `+ extra*WORKER_FACTOR`, затем `amortize(total, delay)`;
   - **`WORKER_FACTOR = 1024`** (`autoworkers.c:70`) — множитель против ошибок округления, при сравнении сокращается;
   - берёт лучшее; `best_newv = 0` и `best_oldv = 9999` — то есть работа с нулевой выгодой не выбирается НИКОГДА.

**Именно этот пункт 2 в нашем агенте отсутствует:** работу клетки у нас выбирает счёт совпадений со списком предпочтений (`_preference_score`), а не ценность клетки для города. Отсюда «работа идёт, роста нет» (13.280): выбирается шахта или дорога, а не то, что поднимет еду города с 2 до 3 и выведет его из размера 1.

### План (прямой перенос, без изобретения)

1. `city_tile_value` — в `brain/ai_default/values.py` буквально.
2. `consider_settler_action` + обход клеток — в `brain/ai_default` новым модулем; новая ценность клетки берётся из УЖЕ построенных нами таблиц (`env/terrain_output.py`, `env/terrain_work_effects.py` — построены на предыдущем этапе).
3. Работа выбирается этим вызовом там, где род выбирается сейчас, — то есть на общем пути, а не в выключенном пути прогноза (ошибка, повторённая трижды: 13.273, 13.280, 13.281).

Варианты и тесты — только там, где буквальный перенос невозможен: где его решение опирается на внутренности сервера, которых у нас нет (`pf_map` — поиск пути, `unit_list_iterate` — чужие рабочие на клетке).
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
