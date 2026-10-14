"""13.313: c в его dai_effect_value — число НАШИХ городов в радиусе, а не единица."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.313. `c` в его оценке эффекта — ЧИСЛО НАШИХ ГОРОДОВ В РАДИУСЕ, а не единица"
BODY = """## 13.313. `c` в его оценке эффекта — ЧИСЛО НАШИХ ГОРОДОВ В РАДИУСЕ, а не единица

### Что нашлось при сверке (13.312 её и требовала)

Сверяя наш `effect_value` с его `dai_effect_value`, я дошёл до самого параметра `c`. Его же
комментарий над функцией (`daieffects.c:136`): **«given the number of cities in range (c)»**.
И он его действительно строит таблицей (`daicity.c:1648-1668`):

```
cities[REQ_RANGE_CITY]   = cities[REQ_RANGE_LOCAL] = 1
cities[REQ_RANGE_PLAYER] = cities[WORLD/ALLIANCE/TEAM] = city_list_size(pplayer->cities)
cities[REQ_RANGE_CONTINENT] = ai->stats.cities[place]
cities[REQ_RANGE_TRADE_ROUTE] = city_num_trade_routes(pcity) + 1
cities[REQ_RANGE_TILE/CADJACENT/ADJACENT] = 0     («Invalid building range»)
```

Наш порт передавал **`c=1` всегда**. Для эффекта радиуса «City» это верно, а для радиуса на всё
царство — нет: ценность занижалась ровно в число городов раз. А таких строк у нас в таблице
эффектов немало: из 270 строк радиус «Player» у 78, «World» у 7 — то есть **85 строк**, ценность
которых считалась как у одного города.

Оговорка про его же код: в `dai_city_want` он передаёт в этот параметр ЗНАЧЕНИЕ ПЕРЕЧИСЛЕНИЯ
радиуса (`range`), а не `cities[range]` — это расходится и с его собственным комментарием, и с
двумя другими вызовами (`daitech.c:310`, `daidata.c:583` передают `1`). Я следую
ЗАДОКУМЕНТИРОВАННОМУ смыслу (число городов) и его таблице, а не похожему на опечатку вызову;
причина выбора записана здесь, чтобы её можно было оспорить.

### Сделано

* `cities_in_range(radius, cities)` — его таблица дословно; неизвестный радиус (в том числе
  `Continent`, счёта по континентам у нас нет) даёт 1 и попадает в `NOTES`, а не в тишину:
  незнание нельзя выдавать за ноль, но и выдумывать число городов нельзя;
* в `improvement_value` радиус берётся у самой строки эффекта (`row[4]` — тот же, что читает
  `output_delta`);
* сторож `test_ai_default_cities_in_range.py` (6 проверок), в том числе: эффект радиуса «Player»
  при четырёх городах ровно в 4 раза ценнее, чем при одном, а радиуса «City» — НЕ зависит от
  размера царства.

### Замер (2 плеча × 2 партии × 45 ходов, после правки)

| плечо | ходы | счёт |
|---|---|---|
| `dof_expansionist` | 45.0 из 45 | 5.0 (было 5.5) |
| `dof_economic` | 45.0 из 45 | 8.0 (было 9.0) |

**Чего замер НЕ доказывает.** Разница в один балл при разбросе стенда 1.0–6.0 не значит ни
улучшения, ни ухудшения. Замер здесь — проверка на обвал, и обвала нет: обе руки проходят 45 из
45, к концу два города размера 2. Основание оставить правку — его исходник и его таблица, а не
эти числа; приписывать ей прирост счёта было бы подгонкой.
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
