"""Убрать утечки съёмочных браузеров (headless Firefox с marionette).

Почему появились: записывающие прогоны, которые я останавливал, не успевали закрыть свой браузер
(`driver.quit()` не вызывался при SIGTERM), и каждый такой Firefox продолжал есть 20–50 % CPU.

Безопасность: берём только процессы, в командной строке которых есть И `marionette`, И `headless`
(обычный пользовательский Firefox так не запускается), и никогда не трогаем себя и своих родителей.
"""
from __future__ import annotations

import os
import signal
import time
from pathlib import Path

SELF = {os.getpid(), os.getppid()}
procs = []
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
        procs.append((pid, cmd.replace("\x00", " ")[:90]))

print(f"найдено съёмочных браузеров: {len(procs)}")
for pid, cmd in procs[:5]:
    print(f"  {pid}: {cmd}")
for pid, _ in procs:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
time.sleep(4)

left = []
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
        left.append(pid)
print(f"осталось: {len(left)}")
for pid in left:
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass