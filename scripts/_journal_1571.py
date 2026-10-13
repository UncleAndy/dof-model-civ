"""13.271: основание обязано быть СТРОГО выше простоя."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.271. Основание обязано быть строго выше простоя"
BODY = """## 13.271. Основание обязано быть строго выше простоя

Первого шага (13.270) не хватило: после того как `build_city`/`found_city` попали в списки всех рук, города **всё равно не основывались**. Живая серия (слот 6300, 15 ходов, `--no-dof`): поселенец юнит/101 ходил `keep_activity` каждый ход, три партии из четырёх — счёт 0, городов 0.

Причина найдена в самом сравнении, а не в списке. Набор действий выбирается как

```
max(descore, key=lambda c: (gen._preference_score(c),
                            sum(c["projected_dof_delta"].values()),
                            c.get("is_reversible", True)))
```

а `_preference_score` — это **счёт совпадений** со списком: `sum(1 for pref in prefs if name.startswith(pref) or pref in name)`. Порядок внутри списка не значит ничего. После правки 13.270 основание и простой давали РАВНОЕ предпочтение — по одному совпадению каждое. Дальше решала обратимость: **простой обратим, основание — нет**, поэтому третий ключ отдавал ход простому. Список был прав, а веса — нет.

Правка: основание получает строгий перевес в `_preference_score` (модульная `FOUNDING_ACTIONS = ('build_city', 'found_city')`, `score += 1.0`). Обоснование — не подгонка: основание города есть решение ИГРЫ, и оно не может проигрывать простому ходу. У всех рук стало 2.0 против 1.0 (у экономической и экспансионистской — против 0.0, там простоя в списке нет вовсе).

Замер после правки (слот 6304, 15 ходов, 3 партии, `--no-dof`): **`turn 1: unit/101/build_city`**, `cities=1, population=2, score=2` (было 0), золото 59; во второй партии `cities=1, population=1, score=1`. Основание разблокировано.

Следующее звено, вскрытое тем же замером и ЕЩЁ НЕ исправленное: город ставит `city/121/produce_Barracks` — ВОЕННОЕ ЗДАНИЕ при населении 1–2. Ворота нужды (`_hold_military_candidates`) собираются из `_military_type_names`, а та читает `attack_strength` у **типов юнитов** (`rules.unit_types`). Здания в это множество не попадают вовсе, поэтому военное здание проходит гейт свободно. Правило нужды должно распространяться и на здания — как в 13.270, «правило обязано действовать везде, где этот род можно выбрать».

Полный набор после правки: **743 passed, 1 xfailed**.
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
