"""13.309: сплошная проверка «мёртвого переноса» — чисто; назван следующий перенос."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.309. Сплошная проверка «мёртвого переноса» — чисто; назван следующий перенос"
BODY = """## 13.309. Сплошная проверка «мёртвого переноса» — чисто; назван следующий перенос

### Сплошная проверка вместо поиска наугад

Класс отказа «перенесено, но не вызывается» встречался за заход **шесть раз** (13.273, 13.280,
13.286, 13.290, 13.301, 13.308). Поэтому проверено сплошь, а не по подозрению:

* по модулям: каждый файл `brain/ai_default/*.py` имеет вызовы с живого пути (`city_manager` 4,
  `tile_outputs` 3, `military` 3, `city_tiles` 2, `values` 2, `effects` 1, `tech` 1,
  `worker_choice` 1, `founder_destination` 1);
* по функциям: у каждой открытой функции посчитаны вызовы ВНЕ её файла. Четыре показались
  мёртвыми (`affected_units`, `requirements_met`, `consider_settler_action`,
  `road_option_from_rules`) — проверка показала, что все четыре вызываются внутри своего
  модуля, то есть работают.

**Итог: действительно мёртвых переносов больше нет.** Дальше этот класс искать не наугад, а
только при появлении новой перенесённой функции — сторожем на уровне исходника
(`test_settler_want_is_wired.py` уже стоит).

### Назван следующий перенос: оценка постройки

Разрыв с эталоном (23 города, население 182, счёт 152.50) остался в **производстве и росте**.
Проверено: из его оценки производства не перенесено ничего — ни `base_want`, ни `dai_city_want`,
ни `building_advisor_choose`; постановку выбираем мы, хотя веса управляющего (`city_manager`)
уже его.

Цепочка его решения, дословно:

1. `building_advisor_choose` (`server/advisors/advbuilding.c:273`) — берёт постройку с наибольшим
   `building_want` среди доступных СЕЙЧАС;
2. `base_want` (`ai/default/daicity.c:1495`) — **контрфакт по всей империи**: добавить постройку и
   просуммировать по городам в радиусе `dai_city_want` минус текущую ценность города;
3. `dai_city_want` (`ai/default/daicity.c:1421`, ~70 строк) — взвешенная сумма выходов города с
   ЕГО приоритетами.

Приоритеты — простые числа из уже перенесённых весов (`server/advisors/advdata.c:499-508`):

```
food_priority = FOOD_WEIGHTING;       shield_priority = SHIELD_WEIGHTING;
gold_priority = TRADE_WEIGHTING;      при науке: luxury 1, science TRADE_WEIGHTING × 1.2;
                                      иначе: luxury TRADE_WEIGHTING, science 1
```

Золото дополнительно взвешивается множителем `(tax − 40) / 14` при ставке налога выше 50 %.

### Что уже есть из мира, а чего нет

Есть: `prod_food`, `prod_shield`, `prod_trade`, `prod_gold`, `upkeep`, размер, склад еды;
эффекты построек — перенесённой моделью (`effects.output_delta`/`improvement_value`).

Нет и обязано быть записано как пропуск, а не как ноль по незнанию: торговые пути, десятина,
загрязнение (`city_pollution`), потери (`city_waste`), ставки налога на город.

### Почему не начато сейчас

Крупная подмена оценки производства — это смена поведения всего выбора постановки; делая её в
хвосте длинного захода, легко получить ровно тот «половину переноса», который трижды оказывался
хуже, чем ничего (13.302, 13.304, 13.306). Перенос начинается с `dai_city_want` как отдельной
функции с тестом на его числах, затем `base_want` поверх неё, затем подключение и замер серией.
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
