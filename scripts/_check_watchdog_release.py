"""Проверка стража завершения в раннере (§13.76): синтетика вместо живого зависания.

Сторож гасит плечо, которое записало ВСЕ запрошенные ходы и перестало писать, — то есть зависло
на уборке. Здесь проверяются все четыре исхода условия, включая положительный контроль, чтобы
«никогда не срабатывал» нельзя было спутать с «сработать не может».
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import importlib.util

spec = importlib.util.spec_from_file_location("ab_runner", ROOT / "scripts" / "v011_ab_city_norm.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

ok = 0
bad = 0


def check(name, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        bad += 1
        print(f"  ФЕЙЛ {name} {detail}")


def make_trace(path: Path, lines: int, quiet_min: float) -> None:
    path.write_text("".join('{"ход": %d}\n' % i for i in range(lines)), encoding="utf-8")
    stamp = time.time() - quiet_min * 60.0
    os.utime(path, (stamp, stamp))


tmp = Path(tempfile.mkdtemp(prefix="eta_watchdog_"))
now = time.time()

full_old = tmp / "full_old.jsonl"
make_trace(full_old, 150, 10)
check("все ходы записаны, запись замерла 10 мин — гасим",
      ab.finished_but_silent(full_old, 150, 180.0, now=now) is True)

full_fresh = tmp / "full_fresh.jsonl"
make_trace(full_fresh, 150, 0.0)
check("все ходы записаны, но запись свежая — НЕ гасим (ещё пишет)",
      ab.finished_but_silent(full_fresh, 150, 180.0, now=now) is False)

short_old = tmp / "short_old.jsonl"
make_trace(short_old, 149, 10)
check("записан 149 из 150 ходов — НЕ гасим (данные неполные)",
      ab.finished_but_silent(short_old, 150, 180.0, now=now) is False)

check("трассы нет — НЕ гасим",
      ab.finished_but_silent(tmp / "нет_такого.jsonl", 150, 180.0, now=now) is False)

edge = tmp / "edge.jsonl"
make_trace(edge, 150, 4)   # 240 с > 180 с — порог перейдён
check("порог 180 с перейдён (240 с) — гасим",
      ab.finished_but_silent(edge, 150, 180.0, now=now) is True)

edge2 = tmp / "edge2.jsonl"
make_trace(edge2, 150, 2)  # 120 с < 180 с
check("порог 180 с не перейдён (120 с) — НЕ гасим",
      ab.finished_but_silent(edge2, 150, 180.0, now=now) is False)

# ── второй признак: плечо вообще не начало партию (§13.108) ──
nlog = tmp / "arm.log"
make_trace(nlog, 1, 10)                       # запись плеча молчит 10 мин
forbidden = tmp / "нет_трассы.jsonl"
check("не начал вовсе: запись молчит, трассы нет — гасим",
      ab.never_started(nlog, forbidden, 240.0, now=now) is True)

nlog_fresh = tmp / "arm_fresh.log"
make_trace(nlog_fresh, 1, 0.5)
check("не начал вовсе: запись свежая — НЕ гасим (плечо работает)",
      ab.never_started(nlog_fresh, forbidden, 240.0, now=now) is False)

zero_trace = tmp / "zero.jsonl"
zero_trace.write_text("", encoding="utf-8")
aged_zero = tmp / "zero_aged.jsonl"
aged_zero.write_text("", encoding="utf-8")
stamp = time.time() - 10 * 60.0
os.utime(aged_zero, (stamp, stamp))
check("не начал вовсе: трасса пуста и СВЕЖАЯ — НЕ гасим (плечо только создало файл)",
      ab.never_started(nlog, zero_trace, 240.0, now=now) is False)
check("не начал вовсе: трасса пуста и молчит больше порога — гасим",
      ab.never_started(nlog, aged_zero, 240.0, now=now) is True)

some_trace = tmp / "some.jsonl"
make_trace(some_trace, 5, 10)
check("начал, но оборвался на середине — НЕ гасим (неполные данные дороже)",
      ab.never_started(nlog, some_trace, 240.0, now=now) is False)

check("не начал вовсе: своей записи нет — НЕ гасим (нечего судить)",
      ab.never_started(tmp / "нет_лога.log", forbidden, 240.0, now=now) is False)

print(f"\nпроверок: {ok + bad}, падений: {bad}")
sys.exit(1 if bad else 0)
