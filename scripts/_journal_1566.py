"""13.266: isolate projection tests from persisted live wedge evidence."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"
SECTION = """## 13.266. Полный набор: причина трёх сбоев — активный реестр клинов

**Наблюдение.** Предыдущий полный запуск дал 716 passed, 1 xfailed, 3 failed. Проверка
`wedged_actions.json` показала запись `unit/build_city`: `seen=3`, `reason=timeout`. В
`estimate_dof_delta` проверка `is_wedged` идёт раньше вычисления эффекта основания, поэтому
активное runtime-свидетельство превращало проекцию в `{}`. Три теста основания проверяли
математику кандидатов, но случайно зависели от накопленных данных живых запусков — отсюда
ложное впечатление о регрессии в выборе основания.

**Исправление изоляции.** В `test_action_mapper.py` для проекционных unit-тестов `is_wedged`
заменён на `False`; в тесте probe-бонуса `test_experiments.py` сделано то же. Файлы и
правила `test_wedged.py` продолжают проверять реестр через собственный временный путь.
Реестр `wedged_actions.json` не удалялся и не редактировался.

**Верификация.** Три ранее падавших теста: 3 passed. Полный набор после изоляции:
719 passed, 1 xfailed, exit 0, 270.44 s. Диагностический smoke-log содержит отправки
`unit/build_city` без отметки `wedged on`; тем не менее активную запись runtime-реестра это
не разрешает само по себе. Контекст клина недостаточен для безопасного общего снятия запрета;
успехи пока не записываются в реестр, а механизм реабилитации не реализован.

**Открыто.** `unit/build_city` с тремя timeout-свидетельствами всё ещё может исключаться
в новых процессах. Нужен отдельный evidence-based этап: точнее привязать клин к контексту и
учитывать подтверждённый успешный `env.step`, сохраняя историю неудач. Не сбрасывать запись
вручную и не объявлять проблему действия решённой только по короткому smoke.
"""

if CAL.exists():
    text = CAL.read_text(encoding="utf-8")
    if "## 13.266." in text:
        head, _, tail = text.partition("## 13.266.")
        _, _, rest = tail.partition("\n## ")
        replacement = head + SECTION
        if rest:
            replacement += "\n## " + rest
        CAL.write_text(replacement, encoding="utf-8")
    else:
        CAL.write_text(text.rstrip() + "\n\n" + SECTION, encoding="utf-8")
    print(f"раздел 13.266 записан | знаков: {len(CAL.read_text(encoding='utf-8'))}")
else:
    print("DOF_CALIBRATION.md не найден")
