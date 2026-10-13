"""13.285: перенесено ядро выбора работы рабочим."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.285. Перенесено ядро выбора работы рабочим: `consider_settler_action`"
BODY = """## 13.285. Перенесено ядро выбора работы рабочим: `consider_settler_action`

Перенос, а не изобретение: `brain/ai_default/worker_choice.py` — `consider_settler_action` (`server/advisors/autoworkers.c:308`) строка в строку, плюс обход клеток из `settler_evaluate_improvements` (там же, стр. 439, тело 468–579) и `WORKER_FACTOR = 1024` (стр. 70). Ценность клетки — уже перенесённый `city_tile_value` (13.284).

### Две ветки его правила, которые я сам сначала перепутал

Это стоит записать, потому что цена ошибки — неверный выбор работы:

1. **Клетка НЕ обрабатывается городом, и лучшая ещё не «в работе»:** сравнивается **ПОЛНАЯ ценность** новой клетки, а не прирост. Его словами: «Getting the best possible total for next citizen to work on is more important than amount tile gets improved» (стр. 344-347). При равной новой ценности предпочитается клетка с **МЕНЬШЕЙ** старой (больше прирост): `old_tile_value < *best_old_tile_value`.
2. **Иначе:** сравнивается **ПРИРОСТ** `new − old`, для необрабатываемой клетки он делится на 2 (`total_value /= 2`), прибавляется `extra * WORKER_FACTOR`, и всё амортизируется: `amortize(total_value, delay)`.

Мои первые тесты ждали прироста там, где исходник сравнивает итог, и падали. **Исправлены тесты под исходник; порт не подгонялся** — в этом и смысл переноса: спорить не с чем, есть текст.

Ещё одно правило, которое легко потерять: `best_newv = 0` и `best_oldv = 9999`. Ноль гарантирует, что работа, ничего не улучшающая, не выбирается НИКОГДА — даже если это единственное, что доступно.

### Что не перенесено и почему (прямой перенос невозможен)

* `pf_map` (поиск пути, `pos.turn`, `pos.moves_left`) — у нас нет карты проходимости в его виде: запаздывание передаёт вызывающий;
* `unit_list_iterate` (чужие рабочие на клетке) и `adv_settler_safe_tile` — в нашем наблюдении их нет: передаются готовым признаком;
* `aw_transform_action_iterate` — перебор доступных работ из правил мира: у нас перебирает вызывающий.

Здесь допустимы варианты и тесты — ровно по правилу владельца: только там, где прямой перенос невозможен.

Охрана: `tests/unit/test_ai_default_worker_choice.py` (10 тестов), включая сторож на сам исходник (читает `autoworkers.c` и требует, чтобы формула и комментарий остались на месте).

### Что осталось

Соединить это с миром: вызывающий должен посчитать ценность клетки ПОСЛЕ работы по нашим таблицам переходов рельефа (`env/terrain_work_effects.py`) и передать в `choose_tile_work`. И поставить вызов туда, где род работы выбирается при `--no-dof` (общий путь), а не в выключенный путь прогноза.
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
