"""Убрать утечки съёмочных браузеров (headless Firefox с marionette) — порт из `v2`.

Почему появились: записывающие прогоны, которые останавливали, не успевали закрыть свой браузер
(`driver.quit()` не вызывался при SIGTERM), и каждый такой Firefox продолжал есть 20–50 % CPU
(измерено в `v2`: 18 утечек). В `v0.11` браузер закрывают `env/video.py:cleanup_env` и обработчик
SIGTERM — этот скрипт нужен для того, что уже утекло до правки.

**Безопасность.** Берём только процессы, в командной строке которых есть И `marionette`, И
`headless` (обычный пользовательский Firefox так не запускается), и никогда не трогаем себя и своих
родителей. Сначала SIGTERM, потом (для упрямых) SIGKILL.

Запуск:
    .venv/bin/python scripts/kill_leaked_browsers.py --dry   # только посмотреть
    .venv/bin/python scripts/kill_leaked_browsers.py         # убрать
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

SELF = {os.getpid(), os.getppid()}
DRY = "--dry" in sys.argv or "--dry-run" in sys.argv
#: Свежий `geckodriver` у живого прогона может не иметь живых детей секунду-две, пока стартует Firefox,
#: поэтому «труп» — это `geckodriver` без живых потомков И старше этого порога (измерено: утечки живут
#: часами, а живой прогон теряет детей только при падении).
CORPSE_MIN_AGE = 90.0
_CLK = os.sysconf("SC_CLK_TCK")


def _stat_fields() -> dict[int, tuple[int, str, str, int]]:
    """pid → (ppid, состояние, cmdline, секунд с запуска)."""
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (FileNotFoundError, ValueError):
        uptime = 0.0
    table: dict[int, tuple[int, str, str, int]] = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        try:
            raw = (d / "stat").read_bytes().decode("utf-8", "replace")
            cmd = (d / "cmdline").read_bytes().decode("utf-8", "replace").replace("\x00", " ")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        rp = raw.rfind(")")
        if rp < 0:
            continue
        parts = raw[rp + 2:].split()
        if len(parts) < 20:
            continue
        state, ppid = parts[0], int(parts[1])
        age = max(0.0, uptime - int(parts[19]) / _CLK) if uptime else 0.0
        table[pid] = (ppid, state, cmd, int(age))
    return table


RUNNERS = ("v011_live_run.py", "v011_ab_city_norm.py", "ab_city_norm.py")


def _in_live_run(pid: int, table: dict[int, tuple[int, str, str, int]]) -> bool:
    """Есть ли в предках живой прогон: у него свой браузер, и трогать его нельзя."""
    seen = 0
    cur = pid
    while cur > 1 and seen < 40:
        entry = table.get(cur)
        if entry is None:
            return False
        ppid, _state, cmd, _age = entry
        if any(r in cmd for r in RUNNERS):
            return True
        cur, seen = ppid, seen + 1
    return False


def leaked() -> list[tuple[int, str]]:
    """Только СИРОТЫ: браузер без живого прогона в предках (иначе убьём работающий прогон)."""
    table = _stat_fields()
    out: list[tuple[int, str]] = []
    for pid, (_ppid, _state, cmd, _age) in table.items():
        if pid in SELF:
            continue
        if "marionette" in cmd and "headless" in cmd and not _in_live_run(pid, table):
            out.append((pid, cmd[:90]))
    return out


def corpses() -> list[tuple[int, str]]:
    """`geckodriver` без живых потомков и старше порога — хвост прогона, который уже не закрыть самому."""
    table = _stat_fields()
    fired: list[tuple[int, str]] = []
    for pid, (ppid, _state, cmd, age) in table.items():
        if pid in SELF or "geckodriver" not in cmd:
            continue
        kids = [q for q, (p, st, c, _a) in table.items() if p == pid and st != "Z"]
        if kids or age < CORPSE_MIN_AGE:
            continue
        fired.append((pid, f"geckodriver без живых детей, возраст {age} с, ppid {ppid}"))
    return fired


def main() -> int:
    procs = leaked()
    print(f"найдено съёмочных браузеров: {len(procs)}")
    for pid, cmd in procs[:5]:
        print(f"  {pid}: {cmd}")
    husks = corpses()
    print(f"найдено мёртвых geckodriver (утечка прошлых прогонов): {len(husks)}")
    for pid, why in husks[:8]:
        print(f"  {pid}: {why}")
    if DRY:
        print("(сухой прогон: ничего не убито)")
        return 0
    for pid, _ in procs:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    for pid, _ in husks:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(4)
    left = [pid for pid, _ in leaked()] + [pid for pid, _ in corpses()]
    print(f"осталось после SIGTERM: {len(left)}")
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
