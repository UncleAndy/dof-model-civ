#!/usr/bin/env python
"""Итог §10.32 по фактическим файлам: M1 (кандидаты), M4 (решения/счёт), смерти.

Записи `*.learn.jsonl` в этой серии оказались пустыми (ошибка сериализации в приборе),
поэтому покрытие/точность/поправки читаются из ЛОГОВ (строки «[обучение]»), а M1 — из
строк «[кандидаты]». Числа метрик — из JSON-сводок.
"""
import glob
import json
import re
import statistics
from collections import Counter, defaultdict

CAND = re.compile(r"\[кандидаты\] ход (\d+): всего (\d+) \(по видам: ([^)]*)\)")


def games(log_path):
    try:
        text = open(log_path, encoding="utf-8").read()
    except FileNotFoundError:
        return []
    return text.split("Reset with port")[1:]


def cands_of(section):
    out = []
    for m in CAND.finditer(section):
        kinds = {}
        for part in m.group(3).split(","):
            bits = part.strip().split()
            if len(bits) == 2 and bits[1].isdigit():
                kinds[bits[0]] = int(bits[1])
        out.append({"turn": int(m.group(1)), "total": int(m.group(2)), **kinds})
    return out


def arm(tag, logs):
    rows = []
    for log in logs:
        for i, section in enumerate(games(log), start=1):
            cs = cands_of(section)
            first = cs[0] if cs else None
            second = cs[1] if len(cs) > 1 else None
            rows.append({
                "игра": f"{log.split('/')[-1]}:{i}",
                "ход1_всего": (first or {}).get("total"),
                "ход1_work": (first or {}).get("work"),
                "ход1_produce": (first or {}).get("produce"),
                "ход2_produce": (second or {}).get("produce"),
                "ход2_всего": (second or {}).get("total"),
            })
    print("=" * 96)
    print(f"{tag}: игр со срезом {sum(1 for r in rows if r['ход1_всего'] is not None)}")
    for key in ("ход1_всего", "ход1_work", "ход1_produce", "ход2_produce"):
        vals = [r[key] for r in rows if r[key] is not None]
        if vals:
            print(f"   {key}: {vals}  среднее {statistics.mean(vals):.2f}")
    return rows


def metrics_arm(tag, json_paths):
    dec, score, turns = [], [], []
    for path in json_paths:
        try:
            data = json.load(open(path))
        except FileNotFoundError:
            continue
        for e in list(data["results"].values())[0]:
            dec.append(float(e.get("decisions_per_turn_mean") or 0))
            score.append(float(e.get("score_cum") or 0))
            turns.append(int(e.get("turns") or 0))
    print(f"{tag}: игр {len(dec)}; решений/ход среднее "
          f"{statistics.mean(dec) if dec else 0:.2f}; счёт сумма "
          f"{sum(score):.1f} (медиана "
          f"{sorted(score)[len(score)//2] if score else 0:.1f}); "
          f"коротких игр (<30 ходов) {sum(1 for t in turns if t < 30)} из {len(turns)}")
    return dec, score


cold_logs = [f"/tmp/learn_cold_s{s}.log" for s in range(1, 6)]
warm_logs = [f"/tmp/learn_warm_s{s}.log" for s in range(1, 4)]
cold_json = [f"/tmp/learn_cold_s{s}.json" for s in range(1, 6)]
warm_json = [f"/tmp/learn_warm_s{s}.json" for s in range(1, 4)]
arm("ХОЛОД (склад пуст, 5 серий)", cold_logs)
arm("ТЁПЛЫЙ (склад проекта, 3 серии)", warm_logs)
metrics_arm("ХОЛОД", cold_json)
metrics_arm("ТЁПЛЫЙ", warm_json)