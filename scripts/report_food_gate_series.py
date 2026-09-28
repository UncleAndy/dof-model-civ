#!/usr/bin/env python
"""Сводка проверки Правила F: по каждой ветви — смерти, действия семейств, еда, счёт.

Ожидания объявлены ДО серии (§10.30):
  (а) ВЫКЛ + правило: смертей 0/12, действий трёх семейств 0, наблюдений surplus<0 = 0,
      счёт и решений/ход НЕ выше прежних;
  (б) ВЫКЛ без правила (контроль): смерти воспроизводятся;
  (в) прогноз + правило: смертей 0, решения есть.

Читаются: JSON-сводка (метрики) + JSONL срезов (действия, города, еда) + лог
(строки «правило F»).
"""
import json
import re
import sys
from collections import Counter, defaultdict

GATED = ("city_unwork", "city_change_specialist", "join_city")


def read_rows(path):
    try:
        return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def summarize(tag, json_path, log_path):
    data = json.load(open(json_path))
    eps = list(data["results"].values())[0]
    rows = read_rows(f"{json_path}.state.jsonl")
    by_game = defaultdict(list)
    for r in rows:
        by_game[r.get("эпизод")].append(r)
    turns = [int(e.get("turns") or 0) for e in eps]
    deaths = sum(1 for e in eps if int(e.get("turns") or 0) < 14)
    acts = Counter()
    surplus_neg = 0
    surplus_zero = 0
    for r in rows:
        for a in r.get("действия_за_ход") or []:
            name = str(a[2]) if len(a) > 2 else ""
            for fam in GATED:
                if name.startswith(fam):
                    acts[fam] += 1
        for c in r.get("my_cities") or []:
            s = c.get("surplus_food")
            if s is None:
                continue
            if float(s) < 0:
                surplus_neg += 1
            elif float(s) == 0:
                surplus_zero += 1
    scores = [float(e.get("score_cum") or 0) for e in eps]
    dec = [float(e.get("decisions_per_turn_mean") or 0) for e in eps]
    errors = sum(1 for e in eps if (e.get("error") or "").strip())
    gate_total = 0
    gate_detail = Counter()
    try:
        for line in open(log_path, encoding="utf-8"):
            if "правило F (еда необратима)" not in line:
                continue
            m = re.search(r"отсечено кандидатов (\d+)", line)
            if m:
                gate_total += int(m.group(1))
            for fam, cnt in re.findall(r"'(city_[a-z_]+|join_city)': (\d+)", line):
                gate_detail[fam] += int(cnt)
    except FileNotFoundError:
        pass
    print("=" * 96)
    print(f"ветвь {tag}: игр {len(eps)}  смертей (ходов < 14) {deaths}  "
          f"ходы {turns}")
    print(f"   действий трёх семейств: {dict(acts) or 'нет'}")
    print(f"   наблюдений с surplus < 0: {surplus_neg};  surplus = 0: {surplus_zero}")
    print(f"   правило отсекло кандидатов: {gate_total}  по семействам: "
          f"{dict(gate_detail) or 'нет'}")
    print(f"   счёт: сумма {sum(scores):.1f}  медиана {sorted(scores)[len(scores)//2]:.1f}")
    print(f"   решений/ход: среднее {sum(dec)/len(dec):.2f}  "
          f"мин {min(dec):.2f}  макс {max(dec):.2f}")
    print(f"   ошибок в записях: {errors}")
    return {"tag": tag, "deaths": deaths, "turns": turns, "acts": dict(acts),
            "surplus_neg": surplus_neg, "surplus_zero": surplus_zero,
            "gate_total": gate_total, "gate_detail": dict(gate_detail),
            "score_sum": sum(scores), "dec_mean": sum(dec) / len(dec)}


if __name__ == "__main__":
    arms = sys.argv[1:] or ["on_off", "off_off", "on_on"]
    out = []
    for tag in arms:
        base = f"/tmp/fgate_{tag}.json"
        try:
            out.append(summarize(tag, base, f"/tmp/fgate_{tag}.log"))
        except FileNotFoundError:
            print(f"ветвь {tag}: нет файла {base}")
    if out:
        print("=" * 96)
        print("ИТОГ: ветвь | смертей | действий семейств | surplus<0 | отсечено | счёт")
        for s in out:
            print(f"  {s['tag']:<8} | {s['deaths']:>3}/12 | "
                  f"{sum(s['acts'].values()):>4} | {s['surplus_neg']:>3} | "
                  f"{s['gate_total']:>4} | {s['score_sum']:.1f}")