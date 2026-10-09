"""Проверка третьего признака сторожа: он обязан СПРОСИТЬ МИР, вошло ли плечо в слот.

Случай, из-за которого правило переписано (§13.117): 09.10 на пилоте 9220 сторож снял плечо A как
«не начавшее партию», а плечо было вошедшим в мир — прокси показывал `Logged in users (count 1)`.
Стенд не нужен: ответ прокси подменяется (`_proxy_users`), а состояния файлов делаются синтетикой.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("ab", ROOT / "scripts" / "v011_ab_city_norm.py")
ab = importlib.util.module_from_spec(SPEC)          # type: ignore[arg-type]
SPEC.loader.exec_module(ab)                          # type: ignore[union-attr]

RESULTS: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'OK  ' if cond else 'ФЕЙЛ'} {name}")
    RESULTS.append((name, bool(cond)))


def stale(path: pathlib.Path, minutes: float = 10.0) -> None:
    stamp = time.time() - minutes * 60.0
    os.utime(path, (stamp, stamp))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "arm.txt"
        trace = tmp / "trace.jsonl"
        log.write_text("Traceback … marionette\n", encoding="utf-8")
        trace.write_text("", encoding="utf-8")
        stale(log)
        stale(trace)

        orig = ab._proxy_users
        try:
            ab._proxy_users = lambda port: 1
            check("плечо ВОШЛО в мир (count 1) — НЕ гасим", not ab.never_started(log, trace, 240.0, port=6000))
            ab._proxy_users = lambda port: 2
            check("в слоте двое (count 2) — НЕ гасим", not ab.never_started(log, trace, 240.0, port=6000))
            ab._proxy_users = lambda port: 0
            check("в слоте пусто (count 0) — гасим", ab.never_started(log, trace, 240.0, port=6000))
            ab._proxy_users = lambda port: None
            check("прокси молчит (незнание) — НЕ гасим", not ab.never_started(log, trace, 240.0, port=6000))
        finally:
            ab._proxy_users = orig
        check("порт не передан (нет спроса) — гасим по старым признакам",
              ab.never_started(log, trace, 240.0))

        fresh = tmp / "fresh.jsonl"
        fresh.write_text("", encoding="utf-8")
        ab._proxy_users = lambda port: 0
        try:
            check("трасса пуста, но СВЕЖАЯ — НЕ гасим", not ab.never_started(log, fresh, 240.0, port=6000))
        finally:
            ab._proxy_users = orig

        check("жёсткий предел объявлен и равен 1800 с", float(ab.STALL_CAP) == 1800.0)
        check("судья знает пометку stalled (отбрасывает такие строки)",
              "stalled" in (ROOT / "scripts" / "v011_ab_city_norm.py").read_text(encoding="utf-8"))

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\nпроверок: {len(RESULTS)}, падений: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
