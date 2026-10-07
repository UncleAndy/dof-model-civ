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
  момент окончания, отсутствие счёта = 0.

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

ARMS = {
    "A": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on"},
    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off"},
}


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
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT)
    return {"arm": arm, "seed": seed, "port": port, "turns_asked": turns, "tag": tag,
            "exit": int(proc.returncode), "log": str(log), "seconds": round(time.time() - started, 1)}


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


def cmd_pairs(args: argparse.Namespace) -> int:
    rows: list[dict] = []
    for i in range(args.pairs):
        seed = args.first_seed + i
        pair = i + 1
        for arm, port in (("A", args.port_a), ("B", args.port_b)):
            tag = f"ab{pair:02d}_{arm}_{seed}"
            rec = _run(arm, seed, port, args.turns, tag)
            rec["pair"] = pair
            rec["score"], rec["turns"] = _last_score(rec)
            rows.append(rec)
            print(f"пара {pair}/2, плечо {arm}: сид {seed}, порт {port}, "
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
    if not OUT.exists():
        print(f"нет файла опыта {OUT} — судить нечего")
        return 1
    per: dict[int, dict[str, float]] = {}
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        per.setdefault(int(rec["pair"]), {})[str(rec["arm"])] = float(rec.get("score") or 0.0)
    pairs = sorted(p for p, arms in per.items() if "A" in arms and "B" in arms)
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
    p_pairs.set_defaults(func=cmd_pairs)
    p_judge = sub.add_parser("judge", help="поставить вердикт офлайн по записанным парам")
    p_judge.set_defaults(func=cmd_judge)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())