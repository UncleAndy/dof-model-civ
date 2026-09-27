#!/usr/bin/env python3
"""Дуэль: несколько наших агентов в ОДНОЙ игре, за разные стороны.

Зачем отдельный раннер. Обычный прогон — один агент против встроенных ИИ; там
разница между вариантами тонет в разнице карт. В дуэли мир, старт, эпоха и
соседи общие, поэтому сравниваются политики, а не удача с картой.

Как это устроено на стенде (проверено 2026-09-26/27):
* игру запускаем мы сами: `aifill 0` (ни одного встроенного ИИ) + `minp N`
  (игра стартует, когда подключились N наших игроков) + `phasemode player`
  (ходы по очереди — штатный режим клиента);
* каждый наш игрок — отдельный ПРОЦЕСС со своим контроллером и своим именем;
* имена — только латиница (`NewPBEMUser` иначе отвечает 400): `duela`, `duelb`;
* `begin_turn_timeout` по умолчанию 30 с — для дуэли мало: host ждёт партнёра и
  сессия умирает. Ставим 380 с;
* обоих запускаем почти одновременно: host должен быть жив, когда вошёл второй.

Статистика парная: считаем разницу ВНУТРИ игры, потом агрегируем разницы. Карта
из разницы вычитается сама, поэтому игре-наблюдению нужна не сотня матчей.

СТАДИЯ 1 — ЗЕРКАЛО (одна политика против себя). Если зеркало даёт систематическую
разницу, дизайн сломан (порядок ходов при `phasemode player`, асимметрия старта),
и любые дуэли на нём ничего не значат. Критерий задан ДО данных (см. ниже).

    python baselines/run_duel.py --games 3 --turns 20 \
        --policy-a dof_expansionist --policy-b dof_expansionist
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metrics.stats import mean  # noqa: E402
from metrics.duel import (  # noqa: E402
    MIRROR_MIN_GAMES,
    ab_verdict,
    mirror_verdict,
)

# ── Порог вердикта: задан ДО данных ─────────────────────────────────────────
#: Меньше этого числа игр вердикта нет: разница по двум играм — это не дизайн,
#: а шум конкретных карт.
MIRROR_MIN_GAMES = 3


class DuelTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise DuelTimeout("дуэль превысила бюджет времени")


def _slot_from_pool(wait: int = 120):
    """Свободный слот через Publite2. Список слотом серверный, поэтому это
    единственный честный способ не попасть на чужую (уже начатую) игру."""
    from civrealm.freeciv.utils.port_utils import Ports
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, wait)
    try:
        return Ports.get()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _worker_cmd(args, slot: int, out_path: Path, username: str,
                policy: str, extra: str) -> list[str]:
    """Команда одного игрока с ЯВНО заданной конфигурацией (вариант X или Y).

    Конфигурация передаётся явно, а не выводится из стороны: между играми стороны
    переставляются (`--swap`), чтобы позиция host/follower не смешивала результат.
    """
    cmd = [
        sys.executable, str(ROOT / "baselines" / "run_real_tournament.py"),
        "--only", policy, "--episodes", "1", "--turns", str(args.turns),
        "--no-auto-port", "--port", str(slot),
        "--duel", "--settle", "0", "--timeout", str(args.match_timeout),
        "--output", str(out_path),
        "--username", username,
        "--aifill", "0", "--minp", "2",
        "--begin_turn_timeout", str(args.begin_turn_timeout),
        "--server_timeout", "120",
    ]
    if args.trace:
        cmd.append("--trace")
    if args.follower_take_player:
        # Follower обязан ВЗЯТЬ свою державу: иначе он наблюдатель, ходы получает,
        # а действий не имеет (измерено: 0 решений за 25 ходов) — и дуэль
        # превращается в «host против наблюдателя».
        cmd.extend(["--follower_take_player", "true"])
    if extra:
        cmd.extend(extra.split())
    return cmd


def _run_game(args, game_no: int) -> dict:
    slot = args.slot if args.slot else _slot_from_pool()
    out_a = Path(f"/tmp/duel_{game_no}_a.json")
    out_b = Path(f"/tmp/duel_{game_no}_b.json")
    log_a = Path(f"/tmp/duel_{game_no}_a.log")
    log_b = Path(f"/tmp/duel_{game_no}_b.log")
    for p in (out_a, out_b):
        p.unlink(missing_ok=True)

    # Варианты: X = policy_a(+extra_a), Y = policy_b(+extra_b). Между играми стороны
    # ПЕРЕСТАВЛЯЮТСЯ, чтобы позиция host/follower (порядок ходов) не смешивала
    # результат: сравнение делается по варианту, а не по стороне.
    x = {"policy": args.policy_a, "extra": args.extra_a or ""}
    y = {"policy": args.policy_b, "extra": args.extra_b or ""}
    swap = bool(args.swap) and game_no % 2 == 0
    cfg_a, cfg_b = (y, x) if swap else (x, y)
    x_side = "b" if swap else "a"

    print(f"[игра {game_no}] слот {slot}: "
          f"A = {cfg_a['policy']}{' ' + cfg_a['extra'] if cfg_a['extra'] else ''} "
          f"({args.name_a}), B = {cfg_b['policy']}"
          f"{' ' + cfg_b['extra'] if cfg_b['extra'] else ''} ({args.name_b})"
          f"{'  [стороны переставлены]' if swap else ''}, ходов {args.turns}",
          flush=True)
    env = dict(os.environ)
    with open(log_a, "wb") as fa:
        pa = subprocess.Popen(
            _worker_cmd(args, slot, out_a, args.name_a, cfg_a["policy"], cfg_a["extra"]),
            stdout=fa, stderr=subprocess.STDOUT, env=env)
    # Почти одновременно: host обязан быть жив, когда входит второй игрок.
    time.sleep(args.launch_gap)
    with open(log_b, "wb") as fb:
        pb = subprocess.Popen(
            _worker_cmd(args, slot, out_b, args.name_b, cfg_b["policy"], cfg_b["extra"]),
            stdout=fb, stderr=subprocess.STDOUT, env=env)

    deadline = time.time() + args.game_timeout
    for proc, name in ((pa, "A"), (pb, "B")):
        while proc.poll() is None and time.time() < deadline:
            time.sleep(2)
        if proc.poll() is None:
            proc.terminate()
            print(f"  {name}: не завершился за {args.game_timeout} с — снят", flush=True)
        else:
            print(f"  {name}: выход {proc.returncode}", flush=True)

    def load(path: Path, side: str) -> dict | None:
        if not path.exists():
            return None
        payload = json.loads(path.read_text())
        for agent, records in (payload.get("results") or {}).items():
            for r in records:
                r["_side"] = side
                r["_agent"] = agent
                return r
        return None

    a, b = load(out_a, "a"), load(out_b, "b")
    return {"game": game_no, "slot": slot, "a": a, "b": b, "swap": swap,
            "x_side": x_side,
            "log_a": str(log_a), "log_b": str(log_b)}


def _usable(rec: dict | None, min_turns: int, require_active: bool = False) -> bool:
    """Годится ли запись стороны.

    `require_active` (дуэль): сторона с НУЛЁМ решений — это не «слабая политика», а
    сломанный инструмент: follower не взял свою державу и остался наблюдателем
    (измерено: рецидив, 1 игра из 4). Такая игра выпадает из пары, иначе она
    раздувает интервал «разницей», которой в игре не было.
    """
    if not rec or rec.get("error"):
        return False
    if float(rec.get("turns") or 0) < min_turns:
        return False
    if require_active and float(rec.get("decisions_per_turn_mean") or 0.0) <= 0.0:
        return False
    return True


def _dead_side(rec: dict | None) -> bool:
    """Сторона не сделала НИ ОДНОГО решения за весь матч — отказ инструмента.

    Отличать от «пассивной политики»: пассивная политика — это НОЛЬ ЦЕЛЫХ решений
    при живой державе, но она всё же делает выборы, и на живых данных её темп был
    0.04–0.05 решения/ход. Ровно 0.00 при `rc=0` и полном числе ходов означает, что
    сторона крутила цикл, но **ход ей не доставался** (та же природа, что у дефекта
    follower'а: державу не взяли). Это не данные о политике, и — в отличие от
    пассивности — остаётся браком даже при `--allow-passive`: там речь о «пусть
    бездействие будет частью эффекта», а не о «пусть сломанный инструмент войдёт
    в интервал разницей, которой в игре не было».
    """
    if not rec or rec.get("error"):
        return False
    return float(rec.get("decisions_per_turn_mean") or 0.0) <= 0.0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=3)
    p.add_argument("--turns", type=int, default=20)
    p.add_argument("--policy-a", default="dof_expansionist")
    p.add_argument("--policy-b", default="dof_expansionist")
    p.add_argument("--extra-a", default="", help="доп. флаги игрока A (напр. --no-curiosity)")
    p.add_argument("--extra-b", default="", help="доп. флаги игрока B")
    p.add_argument("--name-a", default="duela", help="имя учётки (только буквы!)")
    p.add_argument("--name-b", default="duelb")
    p.add_argument("--slot", type=int, default=None, help="пришпилить слот (иначе из пула)")
    p.add_argument("--launch-gap", type=float, default=6.0,
                   help="пауза между запусками A и B: host должен успеть подключиться")
    p.add_argument("--begin-turn-timeout", type=int, default=380)
    p.add_argument("--match-timeout", type=int, default=900)
    p.add_argument("--game-timeout", type=int, default=1200, help="бюджет одной игры")
    p.add_argument("--settle", type=float, default=45.0,
                   help="пауза между играми: Publite2 должен успеть пересоздать игру "
                        "на переиспользуемом слоте, иначе матч умирает на ~5-м ходу "
                        "у обеих сторон (измерено)")
    p.add_argument("--min-turns", type=int, default=10,
                   help="игра короче этого — не данные о политике, а сбой стенда")
    p.add_argument("--require-both-active", dest="require_both_active",
                   action="store_true", default=True,
                   help="игра, где сторона не сделала НИ ОДНОГО решения, — сломанный "
                        "инструмент (follower не взял державу), не результат политики")
    p.add_argument("--allow-passive", dest="require_both_active",
                   action="store_false",
                   help="не фильтровать пассивную сторону (нужно, когда бездействие — "
                        "сама политика, напр. любопытство ВЫКЛ). Сторона с РОВНО "
                        "нулём решений отбраковывается всё равно: это отказ "
                        "инструмента (ход не достался), а не пассивность")
    p.add_argument("--swap", action="store_true",
                   help="переставлять стороны между играми: иначе позиция "
                        "host/follower (порядок ходов) войдёт в результат как эффект")
    p.add_argument("--retries", type=int, default=2,
                   help="повторы несостоявшейся игры (стенд отдал слот без игры)")
    p.add_argument("--follower-take-player", dest="follower_take_player",
                   action="store_true", default=True,
                   help="follower берёт свою державу после старта (иначе он наблюдатель)")
    p.add_argument("--no-follower-take", dest="follower_take_player",
                   action="store_false",
                   help="оставить follower наблюдателем (для сравнения)")
    p.add_argument("--trace", action="store_true")
    p.add_argument("--output", default="duel_results.json")
    args = p.parse_args()

    print("=" * 84)
    print("ДУЭЛЬ: наши политики в одной игре")
    print("=" * 84)
    mirror = (args.policy_a == args.policy_b and args.extra_a == args.extra_b)
    if mirror:
        args.swap = False  # сравнивать нечего: конфигурации совпадают
    print(f"  режим: {'ЗЕРКАЛО (одна политика против себя — контроль дизайна)' if mirror else 'ОЧНАЯ СТАВКА'}")
    if not mirror:
        print(f"  X = {args.policy_a} {args.extra_a or ''}".rstrip())
        print(f"  Y = {args.policy_b} {args.extra_b or ''}".rstrip())
        print(f"  стороны: {'переставляются между играми' if args.swap else 'НЕ переставляются (--swap выключен)'}")
    print(f"  ходов на игру: {args.turns}   игр: {args.games}   "
          f"begin_turn_timeout: {args.begin_turn_timeout} с")
    print(f"  порог вердикта (задан заранее): игр не меньше {MIRROR_MIN_GAMES}")
    if mirror:
        print("  ВНИМАНИЕ: для зеркала смотрите и объём действий (решений/ход) — "
              "разница в объёме сама двигает счёт, поэтому игра с почти "
              "бездействующей стороной это отказ инструмента, а не результат")

    games = []
    game_no = 0
    for i in range(1, args.games + 1):
        if i > 1 and args.settle:
            # Без паузы слот не успевает пересоздать игру, и матч умирает на ~5-м
            # ходу у обеих сторон — это дефект стенда, а не политики.
            print(f"[пауза {args.settle:.0f} с перед игрой {i}]", flush=True)
            time.sleep(args.settle)
        attempts = 0
        while True:
            game_no += 1
            g = _run_game(args, game_no)
            attempts += 1
            ok = (_usable(g["a"], args.min_turns, args.require_both_active)
                  and _usable(g["b"], args.min_turns, args.require_both_active)
                  and not (_dead_side(g["a"]) or _dead_side(g["b"])))
            if ok:
                break
            if attempts > args.retries:
                print(f"  игра не состоялась даже после {attempts} попыток "
                      f"(стенд) — оставляю как отброшенную", flush=True)
                break
            why = ("сторона не сделала ни одного решения — ход не достался "
                   "(отказ инструмента)") if (_dead_side(g["a"]) or _dead_side(g["b"])) \
                else (f"стенд отдал {g['slot']} без игры")
            print(f"  игра не состоялась ({why}) — повтор, попытка {attempts + 1}",
                  flush=True)
            time.sleep(args.settle)
        games.append(g)

    good = [g for g in games
            if _usable(g["a"], args.min_turns, args.require_both_active)
            and _usable(g["b"], args.min_turns, args.require_both_active)
            and not (_dead_side(g["a"]) or _dead_side(g["b"]))]
    bad = [g for g in games if g not in good]
    if bad:
        passive = [g for g in bad
                   if g["a"] and g["b"]
                   and (_usable(g["a"], args.min_turns)
                        and _usable(g["b"], args.min_turns))]
        print(f"\n  отброшено игр: {len(bad)} из {len(games)}"
              + (f" (из них {len(passive)} — сторона не сделала ни одного решения: "
                 f"follower не взял державу)" if passive else ""))

    def vals(key: str, side: str) -> list[float]:
        out = []
        for g in good:
            rec = g[side]
            v = rec.get(key)
            out.append(float(v if v is not None else 0.0))
        return out

    print()
    print(f"{'игра':>5}{'слот':>7}{'X':>8}{'Y':>8}{'Δ X−Y':>9}"
          f"{'решений X/Y':>14}{'сторона X':>11}")
    print("-" * 84)
    diffs = []
    for g in good:
        a, b = g["a"], g["b"]
        # Раскладываем записи по ВАРИАНТАМ, а не по сторонам: при перестановке
        # сторон вариант X может играть за B, и сравнение не должно от этого зависеть.
        x_rec, y_rec = (a, b) if g["x_side"] == "a" else (b, a)
        sx = float(x_rec.get("score_gain") or 0.0)
        sy = float(y_rec.get("score_gain") or 0.0)
        diffs.append(sx - sy)
        dec_x = float(x_rec.get("decisions_per_turn_mean") or 0)
        dec_y = float(y_rec.get("decisions_per_turn_mean") or 0)
        print(f"{g['game']:>5}{g['slot']:>7}{sx:>8.1f}{sy:>8.1f}{sx - sy:>+9.1f}"
              f"{f'{dec_x:.2f}/{dec_y:.2f}':>14}"
              f"{'A' if g['x_side'] == 'a' else 'B':>11}")

    summary: dict = {"games": len(games), "usable": len(good), "mirror": mirror}
    mv = mirror_verdict(diffs) if mirror else ab_verdict(diffs)
    summary.update({"diff_mean": mv['summary']['mean'],
                    "diff_ci": mv['summary']['ci'],
                    "verdict_kind": mv['verdict']})
    print(f"\nпарная разница (X − Y) по счёту: среднее {mv['summary']['mean']:+.2f}, "
          f"95% CI [{mv['summary']['ci'][0]:+.2f}, {mv['summary']['ci'][1]:+.2f}], "
          f"игр {mv['summary']['n']}")
    if mv['verdict'] == 'no_data':
        verdict = f"ВЕРДИКТА НЕТ: {mv['reason']}"
    elif mv['verdict'] == 'clean':
        verdict = f"ЗЕРКАЛО ЧИСТОЕ: {mv['reason']} — дизайн годится для дуэлей"
    elif mv['verdict'] == 'biased':
        verdict = (f"ДИЗАЙН СМЕЩЁН: {mv['reason']} — результаты дуэлей на этом "
                   f"дизайне ничего не значат")
    elif mv['verdict'] == 'no_difference':
        verdict = (f"РАЗЛИЧИЕ НЕ ПОКАЗАНО: {mv['reason']}. Это результат: данные "
                   f"исключают эффект больше указанного интервала")
    else:
        verdict = f"РАЗЛИЧИЕ ЕСТЬ: {mv['reason']}"
    print(verdict)
    if mirror:
        # Ошибку симметрии интересно видеть и по индексу, но индекс канало-зависим:
        # печатаем как контекст, вердикт по нему не выносим.
        ia, ib = vals("avg_total_dof_index", "a"), vals("avg_total_dof_index", "b")
        if ia and ib:
            print(f"  (контекст, не вердикт) индекс: A {mean(ia):.2f} против B {mean(ib):.2f}; "
                  f"разница {mean(ia) - mean(ib):+.2f} — индекс зависит от числа действий, "
                  f"по нему симметрию не судим)")

    summary["verdict"] = verdict
    summary["games_detail"] = [
        {"game": g["game"], "slot": g["slot"],
         "a": {k: g["a"].get(k) for k in ("score_gain", "turns", "avg_total_dof_index",
                                          "decisions_per_turn_mean", "error")} if g["a"] else None,
         "b": {k: g["b"].get(k) for k in ("score_gain", "turns", "avg_total_dof_index",
                                          "decisions_per_turn_mean", "error")} if g["b"] else None}
        for g in games
    ]
    Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nсохранено: {args.output}")
    print("Оговорка: ходы идут по очереди (`phasemode player`), поэтому сам дизайн "
          "требует перестановки сторон между играми — зеркало это и проверяет.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
