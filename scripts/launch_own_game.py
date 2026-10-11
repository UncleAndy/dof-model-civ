#!/usr/bin/env python3
"""Запустить СВОЮ партию: наблюдатель первым, затем N наших агентов.

Правила, добытые опытом (не догадкой), вшиты в порядок запуска:

* **Сторон сколько заказано.** Партия поднимается нами: `aifill 0` (ни одного встроенного ИИ) и
  `minp N` (игра начинается, когда подключились все N наших игроков).
* **Наблюдатель входит ПЕРВЫМ.** В партию, созданную на N мест, N+1-го не пускают
  (`There is no room for new players`), а вход под именем занятого игрока выбил бы нашего же агента
  из-за стола. Поэтому наблюдатель входит в свежую партию до игроков, включает обзор всей карты и
  больше не занимает места (§13.128).
* **Follower обязан взять державу** (`--follower_take_player true`), иначе он наблюдатель без
  действий: измерено 0 решений за 25 ходов.
* **Каждый игрок — отдельный процесс** со своим именем и своей памятью.
* **Процессы живут сами** (`start_new_session=True`): обрыв оболочки не должен уносить прогон —
  иначе теряется уже сыгранное (§13.128).
* **Вывод небуферiзуется** (`-u`): иначе лог пуст, пока процесс жив.

    .venv/bin/python scripts/launch_own_game.py --players 6 --turns 20 --tag own6
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")


def _slot_from_pool() -> int:
    out = subprocess.run(
        [PY, "-c", "from civrealm.freeciv.utils.port_utils import Ports; print(Ports.get())"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=90)
    for line in reversed((out.stdout or "").splitlines()):
        line = line.strip()
        if line.isdigit():
            return int(line)
    raise RuntimeError(f"пул слотов не отдал порт: {out.stdout!r} {out.stderr[-200:]!r}")


def _spawn(cmd: list[str], log: pathlib.Path) -> subprocess.Popen:
    handle = open(log, "wb")
    return subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT,
                            cwd=str(ROOT), start_new_session=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--players", type=int, default=6, help="сколько наших игроков (мест)")
    p.add_argument("--turns", type=int, default=20)
    p.add_argument("--policy", default="random", help="политика всех наших игроков")
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--tag", default="own")
    p.add_argument("--observer", default="yes", choices=["yes", "no"])
    p.add_argument("--observer-minutes", type=float, default=14.0)
    p.add_argument("--launch-gap", type=float, default=45.0,
                   help="сколько ждать после наблюдателя, прежде чем пускать игроков")
    p.add_argument("--begin-turn-timeout", type=int, default=380)
    p.add_argument("--match-timeout", type=int, default=900)
    p.add_argument("--trace", action="store_true")
    p.add_argument("--wait", action="store_true", help="дождаться конца и свести сводку")
    args = p.parse_args()

    slot = args.slot if args.slot else _slot_from_pool()
    tmp = pathlib.Path("/tmp")
    print(f"слот: {slot}   игроков: {args.players}   ходов: {args.turns}   "
          f"политика: {args.policy}   наблюдатель: {args.observer}")

    procs: list[tuple[str, subprocess.Popen]] = []
    if args.observer == "yes":
        log = tmp / f"{args.tag}_{slot}_observer.log"
        # Всевидящая линейка читает мир из кэшей клиента (у наблюдателя ходов нет, §13.129).
        # Терпение входа длинное: игра не начинается, пока не подключатся все N мест, а по умолчанию
        # клиент ждёт пакет хода всего 30 с и умирает ровно на этом ожидании (§13.130).
        cmd = [PY, "-u", str(ROOT / "scripts" / "observer_ruler.py"),
               "--slot", str(slot), "--aifill", "0", "--minp", str(args.players),
               "--poll", "20", "--minutes", str(args.observer_minutes),
               "--server_timeout", "600", "--begin_turn_timeout", "600",
               "--out", str(ROOT / "knowledge" / f"observer_ruler_{args.tag}_{slot}.jsonl")]
        procs.append(("observer", _spawn(cmd, log)))
        print(f"  наблюдатель: pid {procs[-1][1].pid}  (лог {log})")
        time.sleep(max(0.0, args.launch_gap))

    for i in range(1, args.players + 1):
        log = tmp / f"{args.tag}_{slot}_{i}.log"
        out = tmp / f"{args.tag}_{slot}_{i}.json"
        cmd = [PY, "-u", str(ROOT / "baselines" / "run_real_tournament.py"),
               "--only", args.policy, "--episodes", "1", "--turns", str(args.turns),
               "--no-auto-port", "--port", str(slot), "--output", str(out),
               "--duel", "--settle", "0", "--timeout", str(args.match_timeout),
               "--username", f"{args.tag}{i}"[:12], "--aifill", "0",
               "--minp", str(args.players),
               "--begin_turn_timeout", str(args.begin_turn_timeout),
               "--server_timeout", "120", "--follower_take_player", "true"]
        if args.trace:
            cmd.append("--trace")
        procs.append((f"player{i}", _spawn(cmd, log)))
        print(f"  игрок {i}: pid {procs[-1][1].pid}  (лог {log})")

    pid_file = tmp / f"{args.tag}_{slot}.pids"
    pid_file.write_text("\n".join(f"{name} {pr.pid}" for name, pr in procs) + "\n",
                        encoding="utf-8")
    print(f"  номера процессов: {pid_file}")

    if not args.wait:
        print("запущено; прогон живёт сам, обрыв оболочки его не уносит.")
        return 0

    print("жду окончания игроков (наблюдатель закроется сам по часам)...")
    for name, pr in procs:
        try:
            pr.wait()
        except KeyboardInterrupt:
            break
        print(f"  {name}: вышел кодом {pr.returncode}")

    report = subprocess.run(
        [PY, "-u", str(ROOT / "scripts" / "seats_report.py"),
         "--glob", f"/tmp/{args.tag}_{slot}_?.json",
         "--out", str(ROOT / "knowledge" / f"seats_{args.tag}_{slot}.json")],
        cwd=str(ROOT))
    return report.returncode


if __name__ == "__main__":
    raise SystemExit(main())
