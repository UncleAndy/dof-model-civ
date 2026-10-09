"""Остановка всех измерительных прогонов (по команде владельца) — без шаблонов в командной строке.

Почему файлом, а не однострочником: `pgrep -f`/`kill` по шаблону, текст которого стоит в самой команде,
совпадает с командной строкой собственной оболочки и обрывает сессию (дважды 09.10). Здесь процессы
ищутся перебором /proc, а свои предки исключаются.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN_NAMES = ("v011_live_run.py", "v011_ab_city_norm.py", "_scan_slots.py", "ab_pilot")
SELF_EXTRA = ("hermes-snap", "bwrap")


def ancestors() -> set[int]:
    seen: set[int] = set()
    p = os.getpid()
    for _ in range(30):
        seen.add(p)
        try:
            raw = pathlib.Path(f"/proc/{p}/stat").read_text(encoding="utf-8")
            p = int(raw[raw.rfind(")") + 2:].split()[1])
        except Exception:  # noqa: BLE001
            break
    seen.add(p)
    return seen


def find() -> list[tuple[int, str]]:
    self_pids = ancestors()
    out: list[tuple[int, str]] = []
    for d in pathlib.Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) in self_pids:
            continue
        try:
            cmd = (d / "cmdline").read_bytes().decode("utf-8", "replace").replace("\x00", " ").strip()
        except Exception:  # noqa: BLE001
            continue
        if not cmd or any(x in cmd for x in SELF_EXTRA):
            continue
        if any(n in cmd for n in RUN_NAMES):
            out.append((int(d.name), cmd[:110]))
    return out


def main() -> int:
    procs = find()
    print(f"найдено процессов прогонов: {len(procs)}")
    for pid, cmd in procs:
        print(f"  {pid}: {cmd}")
    for pid, _ in procs:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(4)
    left = find()
    print(f"осталось после SIGTERM: {len(left)}")
    for pid, cmd in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(2)
    print(f"осталось после SIGKILL: {len(find())}")

    print("\n── состояние пилота 9222 (последнего) ──")
    rec = ROOT / "knowledge" / "ab_pilot_9222.jsonl"
    rows = [json.loads(l) for l in (rec.read_text("utf-8").splitlines() if rec.exists() else []) if l.strip()]
    print(f"  записей: {len(rows)}")
    for r in rows:
        print("  ", {k: r.get(k) for k in ("arm", "port", "turns", "score", "exit", "released_reason")})
    for t in sorted(ROOT.glob("knowledge/live_trace_9222*")):
        print(f"  трасса {t.name}: {t.stat().st_size} байт")
    print("\n── прокси ──")
    for proxy in (7000, 7001, 7002, 7003):
        try:
            out = subprocess.run(
                ["curl", "-s", "-m", "4", f"http://127.0.0.1:{proxy}/pubstatus"],
                capture_output=True, text=True, timeout=10,
            ).stdout
        except Exception:  # noqa: BLE001
            out = ""
        line = "ответа нет"
        for part in out.replace("<", " <").split("\n"):
            if "Logged in users" in part:
                line = part.strip()[:60]
        print(f"  {proxy}: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
