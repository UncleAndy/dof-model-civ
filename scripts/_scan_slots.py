"""Скан слотов стенда: короткой пробой по 3 хода найти те, которые ИГРАЮТ прямо сейчас.

Почему именно так: состояние слотов меняется во времени (измерено §13.110/13.111: слот то играет 5-12
ходов, то обрывается на 2-м, а прокси занятого слота перезапускается), поэтому решение принимается по
пробе НЕПОСРЕДСТВЕННО перед прогоном, а не по ранее снятому состоянию.

Запуск:  .venv/bin/python scripts/_scan_slots.py [порты через запятую]
Итог печатает таблицей и пишет в knowledge/slot_scan.txt.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
RUN = ROOT / "scripts" / "v011_live_run.py"
OUT = ROOT / "knowledge" / "slot_scan.txt"
PER_PORT_TIMEOUT = 150  # секунд на короткую пробу; проба на 3 хода обычно укладывается в минуту

CLASSES = (
    ("AssertionError", "сервер перестал отвечать"),
    ("BeginTurnTimeoutException", "партия не началась"),
    ("no room for new players", "нет места в партии"),
    ("connected to no player", "игрока не дали"),
    ("Timeout", "таймаут"),
)


def classify(text: str, code: int, turns: int, expected: int) -> str:
    for needle, label in CLASSES:
        if needle in text:
            return label
    if code == 0 and turns >= expected:
        return "ИГРАЕТ"
    if turns:
        return f"играл, оборвался на {turns} (код {code})"
    return f"иное (код {code})"


def play(port: int, turns: int, seed: int) -> tuple[str, int, int]:
    env = dict(os.environ, V011_SERVER_TIMEOUT="120", V011_AIFILL="4")
    try:
        proc = subprocess.run(
            [PY, str(RUN), "--port", str(port), "--seed", str(seed), "--turns", str(turns)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=PER_PORT_TIMEOUT, env=env,
        )
        out, code = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes)
               else (exc.stdout or "")) + " Timeout"
        code = 124
    trace = ROOT / "knowledge" / f"live_trace_{seed}_port{port}.jsonl"
    lines = len(trace.read_text("utf-8").splitlines()) if trace.exists() else 0
    return classify(out, code, lines, turns), code, lines


def main() -> int:
    ports = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1 else
                              ["6000", "6001", "6002", "6003", "6004", "6005", "6006", "6007"])]
    rows: list[str] = [f"скан слотов {time.strftime('%Y-%m-%d %H:%M:%S')} (проба: 3 хода, терпение 120 с, сцена 4)"]
    print(rows[0])
    for port in ports:
        verdict, code, lines = play(port, 3, 93_000 + port)
        row = f"  слот {port}: {verdict} (код {code}, ходов {lines})"
        print(row, flush=True)
        rows.append(row)
    best = [r.split()[1].rstrip(":") for r in rows[1:] if "ИГРАЕТ" in r]
    tail = f"итог: играют слоты {', '.join(best) if best else '— ни один'}"
    print(tail)
    rows.append(tail)
    OUT.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
