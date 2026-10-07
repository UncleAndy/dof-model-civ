"""Ручка сцены: `V011_AIFILL` — сколько ИИ-игроков в партии (скрытые соперники).

Сцена «со скрытыми соперниками» включается одним числом: при `aifill` 8 чужой владелец появляется в
поле зрения уже в первые ходы, при 4 — за 20 ходов не появился ни разу (проверено пробником). Раннер
это число не читал вовсе, поэтому сейчас любой наш прогон играл с четырьмя.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
text = RUN.read_text(encoding="utf-8")
OLD = """    fc_args["client_port"] = port"""
NEW = """    fc_args["client_port"] = port
    # Сцена: число ИИ-игроков. Скрытые соперники — это `aifill` 8, а не 4 по умолчанию.
    fc_args["aifill"] = int(os.environ.get("V011_AIFILL", "4") or 4)"""
if "V011_AIFILL" in text:
    print("ручка уже есть")
else:
    if OLD not in text:
        raise SystemExit("место установки порта не найдено — правка не применена")
    RUN.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("внесена ручка сцены V011_AIFILL")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")