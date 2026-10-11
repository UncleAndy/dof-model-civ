"""Снять наши партии (игроки, наблюдатель, дуэль) — явными номерами, без шаблонов в командной строке.

Почему файлом: `pgrep -f`/`kill` по шаблону, текст которого стоит в самой команде, совпадает с
командной строкой собственной оболочки и обрывает сессию (дважды 09.10). Здесь процессы ищутся перебором
/proc, а свои предки исключаются.
"""
from __future__ import annotations

import os
import pathlib
import signal
import time

MARKERS = ("run_real_tournament.py", "observer_ruler.py", "probe_observer.py", "run_duel.py")


def ancestors() -> set[int]:
    seen: set[int] = set()
    pid = os.getpid()
    while pid and pid not in seen:
        seen.add(pid)
        try:
            stat = pathlib.Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            break
        pid = int(stat.rsplit(")", 1)[1].split()[1])
    return seen


def targets() -> list[tuple[int, str]]:
    skip = ancestors() | {os.getpid()}
    found = []
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in skip:
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if any(m in cmd for m in MARKERS):
            found.append((pid, " ".join(cmd.split("\0"))[:110]))
    return found


def main() -> int:
    found = targets()
    print(f"к снятию: {len(found)}")
    for pid, cmd in found:
        print(f"  {pid}  {cmd}")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(6)
    left = targets()
    for pid, cmd in left:
        print(f"  ещё живо: {pid} — снимаю силой  {cmd}")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(3)
    print("осталось:", len(targets()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
