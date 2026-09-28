#!/usr/bin/env python
"""M1 §10.32 на ПОЛНЫХ сериях (у которых по 2 среза кандидатов на игру).

ХОЛОД s3–s5 и ТЁПЛ s1–s3: по 10 игр × 2 среза в каждой, то есть по 10 пар «ход 1» и
«ход 2» на серию — сравнение ветвей идёт на одинаковом приборе. Серии холод s1–s2
использовали СТАРЫЙ прибор (срез не сбрасывался на игру) и в сравнение не идут.
"""
import re
import statistics

CAND = re.compile(r"\[кандидаты\] ход (\d+): всего (\d+) \(по видам: ([^)]*)\)")


def per_game(log):
    text = open(log, encoding="utf-8").read()
    out = []
    for section in text.split("Reset with port")[1:]:
        dumps = []
        for m in CAND.finditer(section):
            kinds = {}
            for part in m.group(3).split(","):
                bits = part.strip().split()
                if len(bits) == 2 and bits[1].isdigit():
                    kinds[bits[0]] = int(bits[1])
            dumps.append({"turn": int(m.group(1)), "total": int(m.group(2)), **kinds})
        if len(dumps) >= 2:
            out.append(dumps[:2])
    return out


def group(tag, logs):
    first_total, first_work, first_produce, second_produce, second_total = [], [], [], [], []
    for log in logs:
        for d in per_game(log):
            first_total.append(d[0]["total"])
            first_work.append(d[0].get("work", 0))
            first_produce.append(d[0].get("produce", 0))
            second_total.append(d[1]["total"])
            second_produce.append(d[1].get("produce", 0))
    print("=" * 96)
    print(f"{tag}: игр {len(first_total)} (по 2 среза на игру)")
    print(f"  ход 1: всего {statistics.mean(first_total):.2f} "
          f"(все: {first_total})")
    print(f"  ход 1: work {statistics.mean(first_work):.2f}; "
          f"produce {statistics.mean(first_produce):.2f}")
    print(f"  ход 2: всего {statistics.mean(second_total):.2f}; "
          f"produce {statistics.mean(second_produce):.2f} "
          f"(все: {second_produce})")
    print(f"  игр, где на ходу 2 есть ХОТЬ ОДИН оценённый produce: "
          f"{sum(1 for v in second_produce if v)} из {len(second_produce)}")
    return second_produce


cold = group("ХОЛОД s3–s5 (склад: 4 типа)",
             [f"/tmp/learn_cold_s{s}.log" for s in (3, 4, 5)])
warm = group("ТЁПЛ s1–s3 (склад проекта: 13 типов)",
             [f"/tmp/learn_warm_s{s}.log" for s in (1, 2, 3)])
print("=" * 96)
print(f"СРАВНЕНИЕ по второй точке: оценённый produce на ходу 2 — "
      f"тёплый {sum(1 for v in warm if v)}/{len(warm)} игр против "
      f"холодного {sum(1 for v in cold if v)}/{len(cold)} игр")