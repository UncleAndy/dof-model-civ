"""Ограничить оснастку разведки: один шаг за ход.

Причина (поймано пилотом, плечо A): оснастка отвечала действием на КАЖДОЕ решение хода, а ход
допускает много решений — каждый шаг это обмен с сервером игры, и мир не успел: civrealm упал на
`assert self.ws_client.server_timeout_handle == None` в `civ_controller.perform_action`. Игровые
данные при этом целы, падает прогон — но прогон и нужен.

Правило объявляется ДО данных: за ход разведкой идёт НЕ БОЛЕЕ ОДНОГО шага (и одна цель на ход),
остальные решения хода по-прежнему отдаются драйверу. Больше шагов не значит больше разведки:
шаг в невиданную клетку открывает ровно то, что рядом.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
text = RUN.read_text(encoding="utf-8")

ANCHOR = """    if str(os.environ.get("V011_SCOUT", "") or "").strip() not in ("", "0"):
        action = _scout_action(obs, info)
"""
NEW = """    if str(os.environ.get("V011_SCOUT", "") or "").strip() not in ("", "0"):
        # Темп объявлен: один шаг разведки за ход. Иначе на каждый шаг приходится обмен с сервером
        # игры, и мир не успевает за ход (`AssertionError` на `server_timeout_handle`).
        _turn_now = (info or {}).get("turn")
        if _turn_now in _SCOUT_DONE_TURNS:
            action = None
        else:
            action = _scout_action(obs, info)
            if action is not None:
                _SCOUT_DONE_TURNS.add(_turn_now)
"""

if "_SCOUT_DONE_TURNS" in text:
    print("уже ограничено")
else:
    if ANCHOR not in text:
        raise SystemExit("хук разведки не найден — правка не применена")
    text = text.replace(ANCHOR, NEW, 1)
    text = text.replace(
        "_OPEN = 2\n",
        "_OPEN = 2\n#: Ходы, в которых разведка уже сделала свой шаг (правило: один шаг за ход).\n"
        "_SCOUT_DONE_TURNS: set = set()\n",
        1,
    )
    RUN.write_text(text, encoding="utf-8")
    print("внесено: один шаг разведки за ход")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")
lines = RUN.read_text(encoding="utf-8").splitlines()
for i, l in enumerate(lines, 1):
    if "_SCOUT_DONE_TURNS" in l or "Темп объявлен" in l:
        print(f"{i:>4}|{l}")