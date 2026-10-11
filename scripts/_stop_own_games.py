"""Снять наши партии (игроки, наблюдатель, дуэль) — явными номерами.

Два правила, добытые кровью (см. §13.131 в DOF_CALIBRATION.md):

1. **Снимать только то, что само является нашим процессом.** Процесс признаётся нашим, если он запущен
   интерпретатором Python и в его командной строке есть имя нашего скрипта. Оболочки (`bash -c ...`), в
   тексте которых просто упомянуто имя скрипта, нашими НЕ считаются: иначе снимаются оболочки
   собственной сессии — именно так и оборвалась она 11.10.
2. **Свои предки и оболочки распорядителя исключаются** дополнительно — по признакам `hermes-snap`,
   `bwrap`, `AI_AGENT`.

Примерка без снятия: `--list-only`.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import signal
import time

MARKERS = ("run_real_tournament.py", "observer_ruler.py", "probe_observer.py", "run_duel.py")
SELF_EXTRA = ("hermes-snap", "bwrap", "AI_AGENT", "hermes-agent", "kanban")


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


def _cmdline(pid: int) -> str:
    try:
        return pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def targets() -> list[tuple[int, str]]:
    skip = ancestors() | {os.getpid(), 0, 1}
    found = []
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in skip:
            continue
        raw = _cmdline(pid)
        if not raw:
            continue
        argv = [a for a in raw.split("\0") if a]
        if not argv:
            continue
        if any(s in raw for s in SELF_EXTRA):
            continue
        # Правило 1: наш процесс — это ЗАПУЩЕННЫЙ ПИТОНОМ скрипт, а не оболочка с его именем в тексте.
        if "python" not in os.path.basename(argv[0]).lower():
            continue
        if any(m in argv[0] for m in SELF_EXTRA):
            continue
        if any(m in raw for m in MARKERS):
            found.append((pid, " ".join(argv)[:110]))
    return found


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--list-only", action="store_true", help="только показать, не снимать")
    args = p.parse_args()

    found = targets()
    print(f"наших процессов найдено: {len(found)}")
    for pid, cmd in found:
        print(f"  {pid}  {cmd}")
    if args.list_only:
        return 0

    for pid, _cmd in found:
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
