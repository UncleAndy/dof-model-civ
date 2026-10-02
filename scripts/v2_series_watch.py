"""Фоновый сторож серии §10.104: ждёт, пока оба плеча доиграют все 10 партий.

Каждые 60 с проверяет число строк «итог:» в логах плеч. Когда в обоих логах по 10 итогов —
пишет маркер завершения в `knowledge/series_DONE` и выходит. Прогресс дописывает в
`knowledge/series_watch.log`.

Запуск: .venv/bin/python scripts/v2_series_watch.py
"""
from __future__ import annotations

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "knowledge" / "series_A.log"
B = ROOT / "knowledge" / "series_B.log"
DONE = ROOT / "knowledge" / "series_DONE"
WATCH = ROOT / "knowledge" / "series_watch.log"


def count_itos(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(errors="replace").splitlines()
               if "итог:" in line)


def main() -> int:
    if DONE.exists():
        DONE.unlink()
    with WATCH.open("a", encoding="utf-8") as f:
        while True:
            a, b = count_itos(A), count_itos(B)
            f.write(f"{time.strftime('%H:%M:%S')} A={a}/10 B={b}/10\n")
            f.flush()
            if a >= 10 and b >= 10:
                DONE.write_text(f"A={a} B={b} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("DONE\n")
                f.flush()
                return 0
            time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())