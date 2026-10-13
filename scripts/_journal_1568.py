"""13.268: серверный датчик улучшений и перенос worker_want/founder_want."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.268. Датчик улучшений: серверная пара вместо нулей `map.output`"
BODY = """## 13.268. Датчик улучшений: серверная пара вместо нулей `map.output`

Прежний замер работ читал `map.output`, а это поле карты учитывает только террейн и ресурс. На живом стенде (probe4, порт 6001) ирригация на Plains не изменила `map.output` — он остался `(1,1,0)`, — тогда как серверный выход города сменился `(1,1,0) → (2,1,0)`. Значит, любой нуль из `map.output` был утверждением «не измерено», а не «улучшение бесполезно».

Сделано:

* `env/terrain_output.py` — серверный датчик: `server_tile_outputs` читает `output_food/output_shield/output_trade` через существующий `CityWorkTile.output_idx`; `paired_output_deltas` сравнивает только одну клетку в ОДНОМ городе (разные city-контексты несравнимы).
* `env/config.py` — отозваны слепые нули Irrigation/Road/River. Ноль из `map.output` больше не выдаётся за измеренный эффект.
* `env/terrain_work.py` — исправлено несоответствие ключей: дорожные имена искались в секции `extra_*`, а правила живут в `road_*`; ключ `Road` не совпадал с `road`. Дорожная ветка охватывает `Road/Railroad/River` и ищет `ROAD_EFFECTS.get(extra.lower())`. Отсутствующее правило или ненулевые `food_bonus|shield_bonus|trade_bonus` дают `None` (неизвестно), а не ноль. Добавлены постоянные `*_incr_const` поверх террейн-процентных `*_incr`; River имеет `trade_incr_const=1`.
* `scripts/read_terrain_work_effects.py` — экспортёр читает секции `road_*`; итог: 7 террейнов и 3 типа дорог (`road.trade_incr=1`, `river.trade_incr_const=1`, `railroad.shield_bonus=50`).
* `scripts/measure_terrain_effect.py` — переведён с разности `map.output` на `paired_output_deltas(w["server_before"], after_server)`, хранит серверный baseline, печатает `НЕ ИЗМЕРЕНО` при отсутствии пары.
* `scripts/summarize_work_chain.py` — нулевая дельта `map.output` при ИЗМЕНИВШИХСЯ экстрах/террейне теперь помечается «НЕ ИЗМЕРЕНО», а не усредняется как `+0.00/+0.00/+0.00`.
* `scripts/probe_tile_output.py` — диагностический парный probe.

Перенос оценок встроенного ИИ (`brain/forecast/live.py`):

* `worker_want` (порт `ai/default/daicity.c:747-838`): лучшая выгода работы минус половина `FOOD_WEIGHTING` (30) за прокорм рабочего, нормировка `×100/(40+foodbox_cost)`, поправка на плотность `workers/(cities+1)`.
* `founder_want` (порт `ai/default/daisettler.c:1343-1388`): лучшая раскрытая площадка по СЫРОЙ ценности (`city_value_raw`, без нашего порога годности — у него сравнение идёт `cr->result > 0`), дисконт по расстоянию через `PERFECTION=3`.
* Обе заменяют `type_price()` для `Workers`/`Settlers` в `productions()`.

Проверки: целевой набор датчиков и правил — **30 passed**; с `test_worker_role_selection` — **31 passed**; forecast-набор (`test_forecast`, `test_forecast_wiring`, `test_tile_family`, `test_worker_role_selection`) — **33 passed**. Probe4 (`--port 6001 --turns 10`) завершился `PROBE_EXIT=0` и подтвердил живую пару Plains `(1,1,0) → (2,1,0)` при неизменном `map.output`.

Это проверки датчика и переноса оценок. Parity встроенному AI (`normal`, `--no-dof`) не проверялась: турнирная серия не запускалась.
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
