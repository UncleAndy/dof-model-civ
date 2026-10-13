"""13.267: scope wedge evidence to positions and record successful steps."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
TITLE = "## 13.267. Позиционный контекст клина и успешные шаги"
BODY = """## 13.267. Позиционный контекст клина и успешные шаги

`wedged_actions.json` хранил семейные timeout-счётчики без координат. Добавлен контекст позиции для `is_wedged`: `SystemStateMatrix.positions` извлекается из наблюдения, а runner сохраняет позицию до `env.step`, чтобы основание, потребляющее юнит, не теряло её в изменённом post-step observation. Timeout и успешный возврат шага относятся к конкретной позиции; история `seen` сохраняется, другой участок карты остаётся заблокированным, а два новых timeout в той же позиции вновь активируют отсечение.

Проверка: 126 целевых тестов прошли; после фикса snapshot-контекста — ещё 17 целевых тестов; полный набор на финальном коде — **727 passed, 1 xfailed** за 274.86 s. `git diff --check` и `py_compile` завершились без ошибок. Первый полный прогон выявил 46 ошибок только в тестовых monkeypatch-функциях, не принимавших новый keyword `context`; фикстуры исправлены.

В smoke `/tmp/AiScopedWedgeR4_162444.stdout` на порту 6001 (`--episodes 1 --turns 5`) успешно отправлены `unit/build_city` на ходах 1 и 3; `RUN_EXIT=0`, в отчёте `cities=2`. Живой `/home/hermes/projects/AI/DOF-MODEL-CIV/wedged_actions.json` подтверждает `unit/build_city seen=3` и `successes=3`: один позиционный успех вручную зарегистрирован для (8,14) с разрешения владельца, два последующих записаны runtime-кодом для (45,23) и (43,21). Проверка `is_wedged` вернула `False` для всех трёх позиций, но `True` для (9,14) и для вызова без координат. Старые timeout-свидетельства сохранены; `city/city_work seen=53` остаётся отдельной нерешённой записью.

Это smoke-проверка пути действия и регистрации контекста, не сравнение игрового эффекта; parity встроенному AI не оценивалась.
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
