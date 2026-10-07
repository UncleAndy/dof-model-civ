"""Ручка терпения мира: `V011_SERVER_TIMEOUT` — сколько секунд мир ждёт клиента.

Зачем. В сцене с восемью игроками ход тяжелее, и плечо, которое делает лишнее действие за ход, не
укладывается в умолчание `server_timeout: 30` — мир рубит партию на середине
(`AssertionError` на `server_timeout_handle`), то есть плечо обрывается, а это негодный замер.

Это НЕ коэффициент модели и не подгонка: это условие измерения, одинаковое для всех плеч, и оно
объявляется до данных вместе со сценой.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
text = RUN.read_text(encoding="utf-8")
OLD = """    fc_args["aifill"] = int(os.environ.get("V011_AIFILL", "4") or 4)"""
NEW = """    fc_args["aifill"] = int(os.environ.get("V011_AIFILL", "4") or 4)
    # Терпение мира — условие измерения, одинаковое для всех плеч (не коэффициент модели).
    fc_args["server_timeout"] = int(os.environ.get("V011_SERVER_TIMEOUT", "0") or 0) or \\
        fc_args.get("server_timeout", 30)"""
if "V011_SERVER_TIMEOUT" in text:
    print("ручка уже есть")
else:
    if OLD not in text:
        raise SystemExit("место ручки aifill не найдено — правка не применена")
    RUN.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("внесена ручка терпения мира V011_SERVER_TIMEOUT")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")