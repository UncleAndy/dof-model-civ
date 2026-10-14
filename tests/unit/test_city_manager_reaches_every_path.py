"""Сторож §13.329: отправка требований управляющему обязана стоять ДО ветвлений в `act`.

Измерено: вызов стоял после ветки `if ARGS.no_dof:`, а та возвращает ход изнутри себя, —
поэтому на всех приёмочных прогонах (они идут с `--no-dof`) требование управляющему
не отправлялось НИ РАЗУ: город держал излишек еды 0 и не рос.

Это тот же класс, что §13.308 и §13.326: правило живёт там, куда путь не заходит.
Сторож читает исходник и требует:
  1) вызов `_send_city_manager` внутри `act` — раньше первой ветки по `no_dof`;
  2) флаг `--city-manager` включён по умолчанию (его ИИ ставит эти числа всегда,
     `server/cityturn.c:313`, а не по разрешению).
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "baselines" / "run_real_tournament.py"


def _lines() -> list[str]:
    return RUNNER.read_text(encoding="utf-8").splitlines()


def _act_span(lines: list[str]) -> tuple[int, int]:
    """Границы тела `def act(self, obs, info)`: (первая строка тела, последняя)."""
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("def act(self, obs, info)"):
            start = i
            indent = len(line) - len(line.lstrip())
            break
    assert start is not None, "в раннере нет `def act(self, obs, info)`"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        s = lines[j]
        if s.strip() and (len(s) - len(s.lstrip())) <= indent:
            end = j
            break
    return start, end


def test_city_manager_call_precedes_the_no_dof_branch():
    lines = _lines()
    start, end = _act_span(lines)
    body = lines[start:end]

    call = [i for i, s in enumerate(body) if "_send_city_manager(" in s and "def " not in s]
    assert call, "отправки требований управляющему в `act` нет вовсе"

    branch = [i for i, s in enumerate(body) if re.search(r'ARGS,\s*"no_dof"', s)]
    assert branch, "в `act` не найдена ветка по `no_dof` — проверка сторожа устарела"

    assert call[0] < branch[0], (
        "§13.329: отправка требований управляющему стоит ПОСЛЕ ветки `--no-dof`, "
        "которая возвращает ход изнутри себя, — на приёмочных прогонах она мертва. "
        f"строки: отправка {call[0]}, ветка {branch[0]} (в теле act)"
    )


def test_city_manager_is_on_by_default():
    text = RUNNER.read_text(encoding="utf-8")
    m = re.search(r'"--city-manager",[^)]*?default=(\w+)', text, re.S)
    assert m, "не найден флаг `--city-manager`"
    assert m.group(1) == "True", (
        "§13.329: его ИИ ставит требования управляющему ВСЕГДА (`server/cityturn.c:313`), "
        f"поэтому перенос обязан быть включён по умолчанию, а не ждать флага (сейчас {m.group(1)})"
    )
