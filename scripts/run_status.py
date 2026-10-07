"""Статус прогонов: детерминированный вывод для сторожа (cron `monitor`/`no_agent`).

Печатает ТОЛЬКО состояние — без времени, PID и прочего меняющегося: иначе «ничего не
изменилось» выглядело бы как изменение, и сторож будил бы агента на каждом тике.

Вывод пустым не бывает: даже «прогона нет» — это факт, который надо увидеть один раз.
"""
from __future__ import annotations

import glob
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KNOW = ROOT / "knowledge"


def runner_alive() -> bool:
    try:
        out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return False
    return any("v011_ab_city_norm.py pairs" in line for line in out.splitlines())


def traces() -> dict[str, int]:
    out: dict[str, int] = {}
    for f in sorted(glob.glob(str(KNOW / "live_trace_*.jsonl"))):
        p = pathlib.Path(f)
        out[p.name] = p.read_text(errors="replace").count("\n")
    return out


def rows_by_pair() -> dict[str, list[str]]:
    """Строки опыта по парам: какие плечи уже записаны."""
    out: dict[str, list[str]] = {}
    f = KNOW / "ab_scout_aifill8_v2.jsonl"
    if not f.exists():
        return out
    for line in f.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        pair = str(row.get("пара") or row.get("pair") or "?")
        arm = str(row.get("плечо") or row.get("arm") or "?")
        out.setdefault(pair, []).append(arm)
    return out


def main() -> None:
    coarse = "--full" not in sys.argv
    rows = rows_by_pair()
    done = sum(1 for v in rows.values() if len(set(v)) >= 3)
    if coarse:
        # Грубый вид для сторожа: меняется ТОЛЬКО при смене состояния (новая пара,
        # смерть раннера), а не на каждом ходу — иначе «изменилось» каждый тик.
        print("раннер:", "жив" if runner_alive() else "НЕ НАЙДЕН")
        print("закрытых пар:", done, "из 5")
        if rows:
            print("строки опыта по парам:", {k: sorted(v) for k, v in sorted(rows.items())})
        else:
            print("строк опыта нет")
        return

    print("раннер:", "жив" if runner_alive() else "НЕ НАЙДЕН")
    tr = traces()
    active = {k: v for k, v in tr.items()
              if any(k.startswith(f"live_trace_{s}") for s in ("9511", "9512", "9513", "9514"))}
    if active:
        print("текущие трассы:")
        for name, n in sorted(active.items()):
            print(f"  {name}: {n} ходов")
    else:
        print("текущих трасс (9511-9514) нет")
    if rows:
        print("строки опыта по парам:", {k: sorted(v) for k, v in sorted(rows.items())})
    else:
        print("строк опыта нет")
    print("закрытых пар:", done, "из 5")


main()
