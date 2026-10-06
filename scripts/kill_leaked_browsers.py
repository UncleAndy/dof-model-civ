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


def leaked() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        if pid in SELF:
            continue
        try:
            cmd = (d / "cmdline").read_bytes().decode("utf-8", "replace")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if "marionette" in cmd and "headless" in cmd:
            out.append((pid, cmd.replace("\x00", " ")[:90]))
    return out


def main() -> int:
    procs = leaked()
    print(f"найдено съёмочных браузеров: {len(procs)}")
    for pid, cmd in procs[:5]:
        print(f"  {pid}: {cmd}")
    if DRY:
        print("(сухой прогон: ничего не убито)")
        return 0
    for pid, _ in procs:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(4)
    left = [pid for pid, _ in leaked()]
    print(f"осталось после SIGTERM: {len(left)}")
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
