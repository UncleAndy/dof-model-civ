#!/usr/bin/env python
"""Кривая самообучения (§10.32): перенос памяти, накопление, точность, польза.

Главная мера M1 — сколько кандидатов производства прогноз может ОЦЕНИТЬ на ПЕРВОМ ходу
игры (цена типа берётся из склада, поэтому тёплый склад обязан давать больше). Источник —
строки `[кандидаты] ход N: всего K (по видам: …)`, которые печатает `--dump-candidates`.

Дополнительно: записи `<output>.learn.jsonl` (покрытие своих типов, точность памяти,
поправки модели, решения) и метрики игр (`turns`, `score_cum`).
"""
import glob
import json
import re
import statistics
import sys
from collections import defaultdict

KINDS = re.compile(r"по видам: ([^)]*)")
CAND = re.compile(r"\[кандидаты\] ход (\d+): всего (\d+) \(по видам: ([^)]*)\)")


def candidates_by_game(log_path):
    """Список «первый срез кандидатов» по каждой игре файла: {kind: n}."""
    try:
        text = open(log_path, encoding="utf-8").read()
    except FileNotFoundError:
        return []
    games = text.split("Reset with port")
    out = []
    for section in games[1:]:
        m = CAND.search(section)
        if not m:
            out.append(None)
            continue
        kinds = {}
        for part in m.group(3).split(","):
            bits = part.strip().split()
            if len(bits) == 2 and bits[1].isdigit():
                kinds[bits[0]] = int(bits[1])
        out.append({"turn": int(m.group(1)), "total": int(m.group(2)), **kinds})
    return out


def learn_records(path):
    rows = []
    try:
        for line in open(path, encoding="utf-8"):
            if line.strip():
                rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def metrics(path):
    try:
        data = json.load(open(path))
        return list(data["results"].values())[0]
    except (FileNotFoundError, KeyError):
        return []


def report_arm(tag, series_paths, logs, metrics_paths):
    print("=" * 100)
    print(f"ветвь {tag}")
    print(f"  {'серия':<10} {'игр':>4} {'оценённых produce на 1-м ходу':<30} "
          f"{'improve':>8} {'buy':>5} {'знает своих':>12} {'расхожд.':>9} "
          f"{'реш/ход':>8} {'счёт':>6}")
    for spath, lpath, jpath in zip(series_paths, logs, metrics_paths):
        cands = candidates_by_game(lpath)
        rows = learn_records(spath + ".learn.jsonl")
        eps = metrics(jpath)
        produce = [c["produce"] for c in cands if isinstance(c, dict) and "produce" in c]
        improve = [c["improve"] for c in cands if isinstance(c, dict) and "improve" in c]
        buy = [c["buy"] for c in cands if isinstance(c, dict) and "buy" in c]
        known = [len(r.get("покрытие_известно") or []) for r in rows]
        live = [len(r.get("свои_типы") or []) for r in rows]
        mism = sum(len(r.get("точность_расхождения") or []) for r in rows)
        dec = [float(e.get("decisions_per_turn_mean") or 0) for e in eps]
        scores = [float(e.get("score_cum") or 0) for e in eps]
        name = spath.split("/")[-1].replace(".json", "")
        print(f"  {name:<10} {len(eps):>4} "
              f"{str(produce):<30} {str(improve):>8} {str(buy):>5} "
              f"{str([f'{k}/{v}' for k, v in zip(known, live)]):>12} {mism:>9} "
              f"{(statistics.mean(dec) if dec else 0):>8.2f} "
              f"{(sum(scores) if scores else 0):>6.1f}")
    # сводка
    all_produce, all_rows = [], []
    for spath, lpath in zip(series_paths, logs):
        for c in candidates_by_game(lpath):
            if isinstance(c, dict) and "produce" in c:
                all_produce.append(c["produce"])
        all_rows.extend(learn_records(spath + ".learn.jsonl"))
    if all_produce:
        print(f"  ИТОГ: оценённых produce на 1-м ходу — среднее "
              f"{statistics.mean(all_produce):.2f}, мин {min(all_produce)}, "
              f"макс {max(all_produce)} (игр {len(all_produce)})")
    mism = [m for r in all_rows for m in (r.get("точность_расхождения") or [])]
    known = sum(len(r.get("покрытие_известно") or []) for r in all_rows)
    unknown = sum(len(r.get("покрытие_неизвестно") or []) for r in all_rows)
    print(f"  ИТОГ: память знала свои типы {known} раз, не знала {unknown} раз; "
          f"расхождений с живым миром {len(mism)}")
    for m in mism[:6]:
        print(f"    расхождение: {m}")
    return all_produce


if __name__ == "__main__":
    cold_s = sorted(glob.glob("/tmp/learn_cold_s*.json"))
    cold_s = [p for p in cold_s if ".learn." not in p]
    warm_s = sorted(glob.glob("/tmp/learn_warm_s*.json"))
    warm_s = [p for p in warm_s if ".learn." not in p]
    cold = report_arm("ХОЛОД (склад пуст, 5 серий)", cold_s,
                      [p.replace(".json", ".log") for p in cold_s], cold_s)
    warm = report_arm("ТЁПЛЫЙ (склад проекта, 3 серии)", warm_s,
                      [p.replace(".json", ".log") for p in warm_s], warm_s)
    if cold and warm:
        print("=" * 100)
        print(f"СРАВНЕНИЕ M1: тёплый {statistics.mean(warm):.2f} против "
              f"холодного {statistics.mean(cold):.2f} оценённых кандидатов "
              f"производства на первом ходу (ожидание: тёплый БОЛЬШЕ)")