"""Парный опыт (в): узкая норма `v2` против прежней процедуры счёта «сейчас» у города.

ПРОТОКОЛ ОБЪЯВЛЕН ДО ДАННЫХ (§13.57, §13.58); судья читает те же пороги из кода, а не из головы.

Плечи (оба — объявление процедуры счёта, §4.6; правитель меры один):
  A — узкая норма `v2` (§10.91–10.92: «сейчас» = разрешённое миром) + правило §10.99
      (производство входит, только если щиты реально копятся). `DOF_CITY_NORM=narrow`, `DOF_PROD_GATE=on`.
  B — прежняя процедура: «сейчас» включает плиточные назначения, правило §10.99 выключено.
      `DOF_CITY_NORM=wide`, `DOF_PROD_GATE=off`.

Мера — СЧЁТ, ПУБЛИКУЕМЫЙ ИГРОЙ (`player[].score`), а НЕ наш индекс: плечи различаются правителем,
и §3.4.4 запрещает сравнивать числа, полученные под разными правителями.

Вердикт (объявлен до данных):
  медиана попарных разностей (A − B) ≥ 2 очка  И  ≥ 10 % медианы |B| при медиане B ≠ 0  И
  односторонний знаковый тест по турам, где A > B, при p < 0.05.
  Иначе — «эффект не установлен». Вымершие и оборванные партии НЕ выбрасываются: счёт берётся на
  момент окончания, отсутствие счёта = 0. НО плечо, которому стенд не дал партию
  (`released_reason='never_started'` или ноль записанных ходов), в вердикт не идёт вовсе: иначе
  отказ стенда читался бы как результат процедуры счёта. Отброшенные строки печатаются с причиной
  (переобъявлено 09.10.2026, §13.117, до данных серии).

Запуск опыта (долгий, владелец запускает сам):
  <venv>/bin/python scripts/v011_ab_city_norm.py pairs --pairs 10 --first-seed 9100 --turns 150 \
      --port-a 6000 --port-b 6004
Суд вердикта (офлайн, стенд не нужен):
  <venv>/bin/python scripts/v011_ab_city_norm.py judge
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "knowledge" / "ab_city_norm.jsonl"
LOGS = Path("/home/hermes")

#: Объявленные пороги вердикта (ДО данных).
VERDICT_POINTS = 2.0          # медиана попарных разностей ≥ 2 очка
VERDICT_SHARE = 0.10          # и ≥ 10 % медианы |B|
VERDICT_ALPHA = 0.05          # и односторонний знаковый тест p < 0.05

#: Жёсткий предел на плечо (объявлен до данных). Сначала стоял 1800 с — и по паре 9221 снял ДВА
#: ИГРАВШИХ плеча (A: 76 ходов, B: 90 ходов, оба со счётом 9.0). Измеренный темп стенда: 1800 с на
#: 76-90 ходов, то есть ~20-24 с на ход; 150 ходов ≈ 60 мин. Поэтому предел объявлен заново — с запасом
#: на весь заказанный прогон: 5400 с (90 мин). Снимается с пометкой `stalled` и в вердикт не идёт.
STALL_CAP = 5400.0

ARMS = {
    "A": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on", "V011_SCOUT": "1",
          "V011_SCOUT_MODE": "idle-only", "V011_SCOUT_LOG": "1"},
    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off", "V011_SCOUT_LOG": "1"},
    "C": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on", "V011_SCOUT": "1",
          "V011_SCOUT_MODE": "settler-first", "V011_SCOUT_LOG": "1"},
}
for _lvl, _var in (("A", "DOF_AB_ENV_A"), ("B", "DOF_AB_ENV_B")):
    for _item in filter(None, str(os.environ.get(_var, "") or "").split(",")):
        _k, _, _v = _item.partition("=")
        if _k.strip():
            ARMS[_lvl][_k.strip()] = _v.strip()


def _run(arm: str, seed: int, port: int, turns: int, tag: str) -> dict:
    """Один прогон плеча: общий сид на пару, разные порты, своё имя файла."""
    env = dict(os.environ)
    env.update(ARMS[arm])
    env["DOF_RUN_TAG"] = tag
    log = LOGS / f"ab_{tag}.txt"
    cmd = [sys.executable, "scripts/v011_live_run.py", "--port", str(port),
           "--seed", str(seed), "--turns", str(turns)]
    started = time.time()
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                                stdout=fh, stderr=subprocess.STDOUT)
        # Сторож завершения. Замер: плечо может зависнуть ПОСЛЕ последнего хода — свои 150
        # ходов оно записывает, а процесс не выходит (уборка съёмки). Тогда раннер ждёт его
        # вечно, и строка плеча не пишется. Признак вынесен функцией (`finished_but_silent`),
        # чтобы его можно было проверить синтетикой, а не только живым зависанием.
        trace = ROOT / "knowledge" / f"live_trace_{seed}_port{port}_{tag}.jsonl"
        released = False
        released_reason = ""
        while proc.poll() is None:
            time.sleep(20)
            if finished_but_silent(trace, turns, 180.0):
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=30)
                except OSError:
                    pass
                released = True
                released_reason = "finished_but_silent"
                break
            if never_started(log, trace, 240.0, port=port):
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=30)
                except OSError:
                    pass
                released = True
                released_reason = "never_started"
                break
            if time.time() - started > STALL_CAP:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=30)
                except OSError:
                    pass
                released = True
                released_reason = "stalled"
                break
        code = proc.returncode if proc.returncode is not None else -1
    return {"arm": arm, "seed": seed, "port": port, "turns_asked": turns, "tag": tag,
            "exit": int(code), "log": str(log), "seconds": round(time.time() - started, 1),
            "released_by_watchdog": released, "released_reason": released_reason}


def finished_but_silent(trace: Path, turns_asked: int, quiet_seconds: float,
                        now: float | None = None) -> bool:
    """Признак «плечо отработало и зависло на выходе»: все ходы записаны, а запись замерла.

    Само молчание трассы ничего не значит, пока не записаны **все** запрошенные ходы: зависнуть
    может и середина партии, и тогда гасить нельзя — данные неполные. Условие проверяется
    синтетикой (`scripts/_check_watchdog_release.py`), а не только живым зависанием.
    """
    try:
        if not trace.exists():
            return False
        done = sum(1 for _ in trace.open(encoding="utf-8"))
        quiet = (time.time() if now is None else float(now)) - trace.stat().st_mtime
        return done >= int(turns_asked) and quiet > float(quiet_seconds)
    except OSError:
        return False


def _proxy_users(port: int) -> int | None:
    """Сколько клиентов вошло в слот — по странице живости соседнего прокси (7000 + сдвиг).

    Живость и вход живут на странице прокси, а не на игровом порту (правило 45). Здесь это не
    удобство, а признак: он отделяет «плечо внутри мира, просто ещё не написало строку трассы» от
    «плечу не дали партию». Не ответил — возвращаем None, и решение не принимается вовсе.
    """
    import re
    import urllib.request
    proxy = 7000 + (int(port) - 6000)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{proxy}/pubstatus", timeout=5) as fh:
            text = fh.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"Logged in users \(count (\d+)\)", text)
    return int(m.group(1)) if m else None


def never_started(log: Path, trace: Path, quiet_seconds: float, port: int | None = None,
                  now: float | None = None) -> bool:
    """Признак «плечо вообще не начало партию»: ни хода в трассе, ни роста записи, И НЕТ ВХОДА В МИР.

    Дополняет `finished_but_silent`, а не заменяет его. Тот отпускает плечо, записавшее ВСЕ ходы
    (зависло на уборке); этот — плечо, которое не написало НИ ОДНОГО хода и молчит: так выглядит
    слот, отдающий `BeginTurnTimeoutException` (измерено: порты 6002, 6003 на этом стенде).
    Середину партии по-прежнему не гасим: неполные данные дороже потерянного времени.

    **Поправка по данным (серия §13.117).** Пустой трассы и молчащей записи НЕДОСТАТОЧНО: 09.10 на
    пилоте 9220 сторож так снял плечо A (`released_reason='never_started'`, код 143), а плечо при
    этом было ВОШЕДШИМ в мир — прокси 7000 показывал `Logged in users (count 1)`, и рядом плечо B
    за ту же пару написало 22 МБ трассы. Значит обязателен третий признак — спрос у мира: если в
    слоте есть вошедшие, плечо не гасится НИКОГДА. Если прокси не ответил, признак не срабатывает
    (решение не принимается по незнанию).

    Пометка в записи отдельная (`released_reason`), чтобы отпущенное плечо нельзя было принять за
    отработавшее.
    """
    stamp_now = time.time() if now is None else float(now)
    try:
        if not log.exists():
            return False
        if stamp_now - log.stat().st_mtime <= float(quiet_seconds):
            return False
        if trace.exists():
            if trace.stat().st_size > 0:
                return False
            if stamp_now - trace.stat().st_mtime <= float(quiet_seconds):
                return False
        if port is not None:
            users = _proxy_users(int(port))
            if users is None or users > 0:
                return False
        return True
    except OSError:
        return False


def _last_score(record: dict) -> tuple[float, int]:
    """Счёт мира на конец партии и число пройденных ходов — из трассы прогона.

    Отсутствие счёта читается как 0 (вымершая или оборванная партия), а не выбрасывается.
    """
    pattern = f"live_trace_{record['seed']}_port{record['port']}_{record['tag']}.jsonl"
    trace = ROOT / "knowledge" / pattern
    if not trace.exists():
        return 0.0, 0
    score, turns = 0.0, 0
    with trace.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            turns = max(turns, int(row.get("ход") or 0))
            for key in ("счёт_мира", "score"):
                if isinstance(row.get(key), (int, float)):
                    score = float(row[key])
    return score, turns


def _daemonize(args: argparse.Namespace) -> int:
    """Уйти из-под сессии вызывающего: двойной fork + своя сессия + свой лог.

    Долгий опыт не должен зависеть от оболочки, которая его запустила: иначе сигнал сессии убивает
    прогон на середине (проверено: exit −1 после ~35 минут). Пишем `pid`-файл, чтобы живость
    проверялась по процессу, а не по факту запуска.
    """
    log = Path(args.log or "/home/hermes/ab_full.log")
    first = os.fork()
    if first > 0:
        os.waitpid(first, 0)
        return 0
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    with log.open("a", encoding="utf-8") as fh:
        os.dup2(fh.fileno(), 1)
        os.dup2(fh.fileno(), 2)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    Path(args.pid_file or "/home/hermes/ab_run.pid").write_text(str(os.getpid()), encoding="utf-8")
    env = dict(os.environ)
    env["DOF_AB_DETACHED"] = "1"
    argv = [sys.executable] + [a for a in sys.argv if a != "--detach"]
    os.execve(sys.executable, argv, env)
    return 0


def _done_pairs(path: Path) -> set[int]:
    """Пары, у которых уже записаны ОБА плеча: продолжение не должно дублировать прогоны."""
    done: dict[int, set[str]] = {}
    if not path.exists():
        return set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        done.setdefault(int(rec.get("pair") or 0), set()).add(str(rec.get("arm")))
    return {pair for pair, arms in done.items() if {"A", "B"} <= arms}


def cmd_pairs(args: argparse.Namespace) -> int:
    global OUT
    if args.out:
        OUT = Path(args.out)
    if getattr(args, "detach", False) and os.environ.get("DOF_AB_DETACHED") != "1":
        _daemonize(args)
        return 0
    finished = _done_pairs(OUT)
    rows: list[dict] = []
    for i in range(args.pairs):
        seed = args.first_seed + i
        pair = i + 1
        if pair in finished:
            print(f"пара {pair} (сид {seed}) уже записана — пропуск")
            continue
        _ports = {"A": args.port_a, "B": args.port_b, "C": args.port_c}
        for arm in str(args.arms):
            port = _ports[arm]
            tag = f"ab{pair:02d}_{arm}_{seed}"
            rec = _run(arm, seed, port, args.turns, tag)
            rec["pair"] = pair
            rec["score"], rec["turns"] = _last_score(rec)
            rows.append(rec)
            print(f"пара {pair}, плечо {arm}: сид {seed}, порт {port}, "
                  f"ходов {rec['turns']}, счёт мира {rec['score']:g}, выход {rec['exit']}, "
                  f"{rec['seconds']:.0f} с")
            with OUT.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"записано {len(rows)} прогонов в {OUT}")
    return 0


def _sign_test(wins: int, total: int) -> float:
    """Односторонний знаковый тест: P(X ≥ wins) при X ~ Bin(total, 0.5)."""
    if total <= 0:
        return 1.0
    tails = sum(math.comb(total, k) for k in range(wins, total + 1))
    return tails / (2 ** total)


def cmd_judge(args: argparse.Namespace) -> int:
    global OUT
    if getattr(args, "out", ""):
        OUT = Path(args.out)
    if not OUT.exists():
        print(f"нет файла опыта {OUT} — судить нечего")
        return 1
    per: dict[int, dict[str, float]] = {}
    dropped: list[str] = []
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        why = ""
        if str(rec.get("released_reason") or "") in ("never_started", "stalled"):
            why = f"плечо не начало партию ({rec.get('released_reason')})"
        elif int(rec.get("turns") or 0) <= 0:
            why = "ноль записанных ходов"
        if why:
            dropped.append(f"пара {rec.get('pair')} плечо {rec.get('arm')}: {why}")
            continue
        per.setdefault(int(rec["pair"]), {})[str(rec["arm"])] = float(rec.get("score") or 0.0)
    pairs = sorted(p for p, arms in per.items() if "A" in arms and "B" in arms)
    if dropped:
        print(f"отброшено строк: {len(dropped)} — стенд не дал партию, в вердикт такие не идут:")
        for d in dropped[:10]:
            print("   ", d)
    if not pairs:
        print("в файле нет ни одной ПОЛНОЙ пары (нужны оба плеча) — вердикт не ставится")
        return 1
    diffs = [per[p]["A"] - per[p]["B"] for p in pairs]
    median_b = statistics.median([per[p]["B"] for p in pairs])
    median_a = statistics.median([per[p]["A"] for p in pairs])
    med_diff = statistics.median(diffs)
    wins = sum(1 for d in diffs if d > 0)
    p_value = _sign_test(wins, len(diffs))
    share_ok = True if median_b == 0 else abs(med_diff) >= VERDICT_SHARE * abs(median_b)
    established = (med_diff >= VERDICT_POINTS) and share_ok and (p_value < VERDICT_ALPHA)
    print(f"пар {len(pairs)}: A(узкая) медиана {median_a:g}, B(прежняя) медиана {median_b:g}, "
          f"разности {[round(d, 1) for d in diffs]}")
    print(f"медиана разностей {med_diff:g} (порог {VERDICT_POINTS:g}); "
          f"доля от медианы |B| {'проходит' if share_ok else 'не проходит'} "
          f"(порог {VERDICT_SHARE:.0%} при медиане B {median_b:g}); "
          f"знаковый тест: побед A {wins} из {len(diffs)}, p = {p_value:.4f} (порог {VERDICT_ALPHA})")
    print("ВЕРДИКТ: " + ("узкая норма лучше — эффект установлен" if established
                         else "эффект не установлен"))
    return 0 if established else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Парный опыт (в): узкая норма против прежней процедуры")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_pairs = sub.add_parser("pairs", help="запустить пары (долго; стенд занят на всё время)")
    p_pairs.add_argument("--pairs", type=int, default=10)
    p_pairs.add_argument("--first-seed", type=int, default=9100)
    p_pairs.add_argument("--turns", type=int, default=150)
    p_pairs.add_argument("--port-a", type=int, default=6000)
    p_pairs.add_argument("--port-b", type=int, default=6004)
    p_pairs.add_argument("--port-c", type=int, default=6005)
    p_pairs.add_argument("--arms", default="ABC",
                         help="какие плечи гонять: ABC (по умолчанию) или AB для повтора по двум рукам")
    p_pairs.add_argument("--out", default="", help="свой файл опыта (пилоту — своё имя, а не общее)")
    p_pairs.add_argument("--detach", action="store_true",
                         help="уйти из-под сессии (двойной fork + своя сессия): долгий опыт не гибнет с оболочкой")
    p_pairs.add_argument("--log", default="", help="куда писать вывод при --detach")
    p_pairs.add_argument("--pid-file", default="", help="файл с pid отделённого опыта")
    p_pairs.set_defaults(func=cmd_pairs)
    p_judge = sub.add_parser("judge", help="поставить вердикт офлайн по записанным парам")
    p_judge.add_argument("--out", default="", help="какой файл опыта судить")
    p_judge.set_defaults(func=cmd_judge)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())