"""13.270: рука без действия основания меряет список, а не игру."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.270. Рука без основания меряет список предпочтений, а не игру"
BODY = """## 13.270. Рука без основания меряет список предпочтений, а не игру

Серия `--no-dof` (21 партия, слоты 6315–6330, 30 ходов) вскрыла причину, по которой parity с встроенным ИИ нельзя было измерять вовсе: **четыре руки из пяти не могут основать город по построению**.

При `--no-dof` прогноз выключен, и выбор идёт ровно предпочтением стратегии (`HeuristicGenerator._preference_score`). В списках `preferred_unit_actions` не было ни `build_city`, ни `found_city`:

| рука | список юнита | основание |
|---|---|---|
| defensive | fortify, fortress, sentry, keep_activity | нет |
| economic | road, railroad, mine, plant, cultivate, goto | нет |
| technological | keep_activity, fortify, sentry | нет |
| diplomatic | keep_activity, fortify, sentry | нет |
| expansionist | found_city, build_city, road, … | да |

След следа: `unit/103/keep_activity`, `unit/113/keep_activity` … на каждом ходу девяти ходов подряд, и `gov/0/set_sci_lux_tax`. Итог стенда по такой руке — **счёт 0, городов 0, юнитов 0**, тогда как случайная политика (`random`) на той же серии взяла город на первом ходу и закончила со счётом 7 (2 города, 14 юнитов). Это ровно тот случай, о котором предупреждает справочник по встроенному ИИ: **список предпочтений — часть политики**, и рука с пустым по основанию списком меряет список, а не игру.

Правка: `build_city`/`found_city` добавлены первыми в список юнита каждой руки (4 замены). Основание города — решение ИГРЫ, а не доменная склонность, поэтому список без него недопустим у любой руки.

Охрана (TDD, RED → GREEN): `tests/unit/test_strategy_founding.py` —
`test_every_strategy_can_found_a_city` (состав списка) и
`test_preference_score_rewards_founding_for_every_strategy` (живой путь оценки: `build_city` обязан получать ненулевую оценку у КАЖДОЙ руки, а не только быть в списке).

Оговорка о данных серии: её результаты для рук `dof_*` **негодны** — они сняты до правки. Серия остановлена по явным PID (конкурировала за стенд со вторым прогоном). Годная серия не запускалась.
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
