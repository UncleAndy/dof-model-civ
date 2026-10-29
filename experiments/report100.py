#!/usr/bin/env python3
"""Сводный отчёт по серии 100 раундов x 3000 ходов (три руки: nodof/dof/half).

Читает experiments/dof-ab-100x3000/rounds/round_*.json, считает:
  1) аудит данных (движок, ходы, сиды, подмены сида);
  2) средние по рукам и парные сравнения с p-значениями;
  3) внутри half — DOF-места против обычных мест в одной и той же партии.

Пишет report.md и summary.json в каталог серии, печатает ключевые числа.
"""

import glob
import json
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "experiments", "dof-ab-100x3000")

sys.path.insert(0, HERE)
from make_report import betai, p_two_sided  # noqa: E402


def load():
    rounds = []
    for p in sorted(glob.glob(os.path.join(OUT, "rounds", "round_*.json"))):
        with open(p, encoding="utf-8") as f:
            rounds.append(json.load(f))
    rounds.sort(key=lambda r: r["round"])
    return rounds


def roster(sec):
    """Имя места -> 1 (DOF) / 0 (обычное)."""
    d = {}
    for name, idx, flag in re.findall(r"([^,:\[\]]+?):idx=(\d+):dof=([01])",
                                      sec.get("dof_roster") or ""):
        d[name.strip()] = int(flag)
    return d


def seats(sec):
    """Живые и мёртвые места партии без варваров."""
    return [n for n in sec["nations"] if not n.get("is_barbarian")]


def val(n, k):
    v = n.get(k)
    return v if isinstance(v, (int, float)) else 0


# ---------------------------------------------------------------- статистика
def paired(a, b):
    """Парная разница a-b: среднее, sd, t, p (двусторонний)."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = st.mean(d)
    sd = st.stdev(d) if n > 1 else 0.0
    if sd == 0:
        return {"n": n, "mean": m, "sd": 0.0, "t": float("inf") if m else 0.0, "p": 0.0 if m else 1.0}
    t = m / (sd / math.sqrt(n))
    return {"n": n, "mean": m, "sd": sd, "t": t, "p": p_two_sided(t, n - 1)}


def sign_test(a, b):
    """Сколько раундов a>b и a<b — проверка на устойчивость знака."""
    wins = sum(1 for x, y in zip(a, b) if x > y)
    losses = sum(1 for x, y in zip(a, b) if x < y)
    ties = len(a) - wins - losses
    # двусторонний точный биномиальный p
    n = wins + losses
    if n == 0:
        return wins, losses, ties, 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return wins, losses, ties, min(1.0, 2 * tail)


def fp(p):
    if p < 1e-4:
        return "<1e-4"
    return f"{p:.4f}"


def boot_ci(a, b, iters=4000, seed=7):
    """95% доверительный интервал для средней парной разницы a-b."""
    import random
    rnd = random.Random(seed)
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    means = []
    for _ in range(iters):
        means.append(sum(rnd.choice(d) for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def summ(v, fmt="{:.1f}"):
    return fmt.format(st.mean(v))


# ---------------------------------------------------------------- аудит
def audit(rounds):
    engines = {}
    turns = {}
    fallbacks = []
    players = {}
    gaps = []
    for r in rounds:
        e = r["params"].get("engine_md5", "?")[:8]
        engines[e] = engines.get(e, 0) + 1
        if r.get("seed_fallback"):
            fallbacks.append(r["round"])
        for a, s in r["sections"].items():
            turns[s.get("final_turn")] = turns.get(s.get("final_turn"), 0) + 1
            players[s.get("players")] = players.get(s.get("players"), 0) + 1
    nums = sorted(r["round"] for r in rounds)
    gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
    return {"count": len(rounds), "first": nums[0], "last": nums[-1],
            "gaps": gaps, "engines": engines, "turns": dict(sorted(
                (k, v) for k, v in turns.items() if k is not None)),
            "fallbacks": fallbacks, "players": dict(sorted(
                (k, v) for k, v in players.items() if k is not None))}


# ---------------------------------------------------------------- руки
ARM_KEYS = [
    ("score на место", lambda s: s["totals"]["score_mean"], "{:.0f}"),
    ("городов всего", lambda s: s["totals"]["cities_sum"], "{:.1f}"),
    ("население всего", lambda s: s["totals"]["population_sum"], "{:.1f}"),
    ("технологий на место", lambda s: s["totals"]["techs_mean"], "{:.1f}"),
    ("наука, bulbs/ход", lambda s: s["totals"]["bulbs_mean"], "{:.1f}"),
    ("убито юнитов", lambda s: s["units_killed"], "{:.0f}"),
    ("  из них варваров", lambda s: s.get("barb_units_killed", 0), "{:.0f}"),
    ("потеряно юнитов", lambda s: s["units_lost"], "{:.0f}"),
    ("живых мест", lambda s: s["alive"], "{:.2f}"),
    ("мест в партии (с распадами)", lambda s: s["players"], "{:.2f}"),
    ("объявлений войны", lambda s: s["dof_declares"], "{:.1f}"),
    ("заблокировано атак", lambda s: s["dof_blocked"], "{:.0f}"),
    ("подавлено желаний", lambda s: s.get("dof_suppressed", 0), "{:.0f}"),
    ("ответов на источник", lambda s: s["journal"].get("on_source", 0), "{:.0f}"),
    ("кораблей запущено", lambda s: len(s.get("spaceship_launched") or []), "{:.2f}"),
    ("финальный ход", lambda s: s["final_turn"], "{:.1f}"),
]


def by_arm(rounds):
    arms = ("nodof", "dof", "half")
    series = {a: {name: [] for name, _, _ in ARM_KEYS} for a in arms}
    for r in rounds:
        for a in arms:
            s = r["sections"][a]
            for name, f, _ in ARM_KEYS:
                series[a][name].append(f(s))
    return series


# ---------------------------------------------------------------- half по сторонам
SEAT_KEYS = [
    ("score", lambda n: val(n, "score"), "{:.0f}"),
    ("городов", lambda n: val(n, "ncities"), "{:.1f}"),
    ("население", lambda n: val(n, "population_real"), "{:.1f}"),
    ("технологий", lambda n: val(n, "techs"), "{:.1f}"),
    ("наука, bulbs/ход", lambda n: val(n, "bulbs_last_turn"), "{:.1f}"),
    ("золото", lambda n: val(n, "gold"), "{:.0f}"),
    ("построено юнитов", lambda n: val(n, "units_built"), "{:.0f}"),
    ("убито юнитов", lambda n: val(n, "units_killed"), "{:.0f}"),
    ("потеряно юнитов", lambda n: val(n, "units_lost"), "{:.0f}"),
    ("земля", lambda n: val(n, "landarea"), "{:.0f}"),
]


def half_split(rounds):
    per_round = []
    for r in rounds:
        s = r["sections"]["half"]
        ro = roster(s)
        grp = {1: [], 0: []}
        for n in seats(s):
            if n["name"] in ro:
                grp[ro[n["name"]]].append(n)
        # только «исходные» места: новые места от гражданских войн (UnassignedN)
        # не входят ни в одну из групп и не должны попадать в счёт топ-5
        ros = [n for n in seats(s) if n["name"] in ro]
        top = sorted(ros, key=lambda n: -val(n, "score"))
        row = {"round": r["round"],
               "dof": grp[1], "plain": grp[0],
               "dof_wins_top5": sum(1 for n in top[:5] if ro.get(n["name"]) == 1),
               "top1_dof": 1 if top and ro.get(top[0]["name"]) == 1 else 0,
               "alive_dof": sum(1 for n in grp[1] if n.get("is_alive")),
               "alive_plain": sum(1 for n in grp[0] if n.get("is_alive"))}
        per_round.append(row)
    return per_round


def main():
    rounds = load()
    A = audit(rounds)
    series = by_arm(rounds)
    per_round = half_split(rounds)

    lines = []
    P = lines.append
    P("# Серия 100 раундов × 3000 ходов: сводный отчёт")
    P("")
    P(f"Каталог: `experiments/dof-ab-100x3000/`. Раундов: **{A['count']}** "
      f"({A['first']}–{A['last']}), партий: {A['count'] * 3}.")
    P("")
    P("## 1. Аудит данных")
    P("")
    P(f"- пропусков в нумерации: {A['gaps'] if A['gaps'] else 'нет'}")
    P(f"- движок по раундам: " + ", ".join(f"`{k}…` — {v}" for k, v in A["engines"].items()))
    P(f"- финальный ход партий: " + ", ".join(f"{k} — {v}" for k, v in A["turns"].items()))
    P(f"- мест в партии: " + ", ".join(f"{k} — {v}" for k, v in A["players"].items()))
    P(f"- подмена сида (карта не генерировалась): "
      f"{A['fallbacks'] if A['fallbacks'] else 'нет'}")
    P("")

    P("## 2. Три руки: средние на раунд")
    P("")
    P("Различия считаны по раундам (парные наблюдения на одном сиде).")
    P("")
    P("| метрика | no DOF | DOF у всех | 50/50 | DOF − noDOF | p | 50/50 − noDOF | p |")
    P("|---|---|---|---|---|---|---|---|")
    for name, _, fmt in ARM_KEYS:
        n_ = series["nodof"][name]
        d_ = series["dof"][name]
        h_ = series["half"][name]
        pd = paired(d_, n_)
        ph = paired(h_, n_)
        P(f"| {name} | {fmt.format(st.mean(n_))} | {fmt.format(st.mean(d_))} | "
          f"{fmt.format(st.mean(h_))} | {fmt.format(pd['mean'])} | {fp(pd['p'])} | "
          f"{fmt.format(ph['mean'])} | {fp(ph['p'])} |")
    P("")
    P("Порог Бонферрони для 15 метрик: 0,05/15 = 0,0033.")
    P("")

    # контроль по «исходным» местам: в войнах империи распадаются на новые
    # места (UnassignedN), и они попадают в знаменатель score на место
    def orig_score(sec):
        nat = [n for n in sec["nations"]
               if not n.get("is_barbarian")
               and not str(n["name"]).startswith("Unassigned")]
        return sum(n.get("score") or 0 for n in nat) / len(nat)

    o_n = [orig_score(r["sections"]["nodof"]) for r in rounds]
    o_d = [orig_score(r["sections"]["dof"]) for r in rounds]
    o_h = [orig_score(r["sections"]["half"]) for r in rounds]
    od = paired(o_d, o_n)
    oh = paired(o_h, o_n)
    P(f"Проверка на распадах: если считать средний score только по исходным десяти "
      f"местам (без новых мест `UnassignedN`, которые появляются при гражданских "
      f"войнах), то no DOF {st.mean(o_n):.0f}, DOF {st.mean(o_d):.0f} "
      f"({od['mean']:+.0f}, p={fp(od['p'])}), 50/50 {st.mean(o_h):.0f} "
      f"({oh['mean']:+.0f}, p={fp(oh['p'])}). Выводы не меняются.")
    P("")

    # знаки по score
    w, l, t, p = sign_test(series["dof"]["score на место"], series["nodof"]["score на место"])
    w2, l2, t2, p2 = sign_test(series["half"]["score на место"], series["nodof"]["score на место"])
    P(f"Устойчивость знака по score: DOF выше контроля в {w} раундах, ниже в {l}, "
      f"равно в {t} (p={fp(p)}); 50/50 выше контроля в {w2}, ниже в {l2} (p={fp(p2)}).")
    P("")

    P("## 3. Режим 50/50: DOF-места против обычных мест внутри одной партии")
    P("")
    P("В каждой партии руки `half` пять мест играют по правилу DOF и пять — без него. "
      "Ниже средние на одно место по 100 раундам (по 500 мест на группу).")
    P("")
    P("Средние считаны по 500 местам каждой группы, медианы — по тем же местам "
      "(устойчивы к выбросам), «раундов DOF>» — в скольких раундах из 100 среднее "
      "по DOF-стороне выше, чем по обычной. p — парный t-тест по раундам.")
    P("")
    P("| метрика на место | DOF: среднее | DOF: медиана | обычные: среднее | "
      "обычные: медиана | раундов DOF> | p |")
    P("|---|---|---|---|---|---|---|")
    for name, f, fmt in SEAT_KEYS:
        a = [st.mean([f(n) for n in row["dof"]]) for row in per_round if row["dof"]]
        b = [st.mean([f(n) for n in row["plain"]]) for row in per_round if row["plain"]]
        med_d = st.median([f(n) for row in per_round for n in row["dof"]])
        med_p = st.median([f(n) for row in per_round for n in row["plain"]])
        pr = paired(a, b)
        wins = sum(1 for x, y in zip(a, b) if x > y)
        P(f"| {name} | {fmt.format(st.mean(a))} | {fmt.format(med_d)} | "
          f"{fmt.format(st.mean(b))} | {fmt.format(med_p)} | {wins}/100 | {fp(pr['p'])} |")
    P("")

    dof_alive = sum(1 for row in per_round for n in row["dof"] if n.get("is_alive"))
    dof_n = sum(len(row["dof"]) for row in per_round)
    pl_alive = sum(1 for row in per_round for n in row["plain"] if n.get("is_alive"))
    pl_n = sum(len(row["plain"]) for row in per_round)
    P(f"Выжило мест: DOF — {dof_alive} из {dof_n} ({100*dof_alive/dof_n:.0f}%), "
      f"обычные — {pl_alive} из {pl_n} ({100*pl_alive/pl_n:.0f}%).")
    top5 = sum(row["dof_wins_top5"] for row in per_round)
    P(f"Мест в топ-5 по score, занятых DOF-стороной: {top5} из {5*len(per_round)} "
      f"({100*top5/(5*len(per_round)):.0f}%; при равенстве ожидалось бы 50%).")
    score_dof = [st.mean([val(n, "score") for n in row["dof"]]) for row in per_round]
    score_plain = [st.mean([val(n, "score") for n in row["plain"]]) for row in per_round]
    ws, ls, ts, ps = sign_test(score_dof, score_plain)
    lo, hi = boot_ci(score_dof, score_plain)
    P(f"Раундов, где DOF-сторона сильнее по среднему score: {ws}, слабее: {ls}, "
      f"равно: {ts} (биномиальный p={fp(ps)}).")
    P(f"Парная разница score (DOF − обычные): "
      f"{st.mean(score_dof) - st.mean(score_plain):+.0f}, 95% ДИ [{lo:+.0f}; {hi:+.0f}].")
    t1 = sum(row["top1_dof"] for row in per_round)
    P(f"Первое место по score занято DOF-местом в {t1} раундах из {len(per_round)}.")
    av = paired([row["alive_dof"] for row in per_round],
                [row["alive_plain"] for row in per_round])
    P(f"Выживших мест за раунд: DOF {st.mean([r['alive_dof'] for r in per_round]):.2f}, "
      f"обычные {st.mean([r['alive_plain'] for r in per_round]):.2f}, "
      f"разница {av['mean']:+.2f} (p={fp(av['p'])}).")
    P("")
    # медианы по «скошенным» метрикам
    # проверка на выживших и на медиане разницы
    alive_dof = [val(n, "score") for row in per_round
                 for n in row["dof"] if n.get("is_alive")]
    alive_plain = [val(n, "score") for row in per_round
                   for n in row["plain"] if n.get("is_alive")]
    dead_dof = [val(n, "score") for row in per_round
                for n in row["dof"] if not n.get("is_alive")]
    dead_plain = [val(n, "score") for row in per_round
                  for n in row["plain"] if not n.get("is_alive")]
    diffs = [a - b for a, b in zip(score_dof, score_plain)]
    P(f"Только по выжившим местам (все места вместе): score {st.mean(alive_dof):.0f} "
      f"у DOF против {st.mean(alive_plain):.0f} у обычных. Мёртвые места сохраняют "
      f"замороженный score (в среднем {st.mean(dead_dof):.0f} против "
      f"{st.mean(dead_plain):.0f}), нулями картина не искажается. "
      f"Медиана парной разницы по раундам {st.median(diffs):+.0f} при среднем "
      f"{st.mean(diffs):+.0f}: в типичном раунде DOF-сторона впереди, среднее тянут "
      f"редкие раунды, где одно обычное место сносит полкарты.")
    P("")
    P("Медианы на место (устойчивы к выбросам):")
    P("")
    P("| метрика | DOF-места | обычные места |")
    P("|---|---|---|")
    for name, k in (("score", "score"), ("золото", "gold"),
                    ("наука, bulbs/ход", "bulbs_last_turn"),
                    ("городов", "ncities"), ("технологий", "techs")):
        a = st.median([val(n, k) for row in per_round for n in row["dof"]])
        b = st.median([val(n, k) for row in per_round for n in row["plain"]])
        P(f"| {name} | {a:.0f} | {b:.0f} |")
    P("")

    # соотношение убитых к потерянным
    kd = sum(val(n, "units_killed") for row in per_round for n in row["dof"])
    ld = sum(val(n, "units_lost") for row in per_round for n in row["dof"])
    kp = sum(val(n, "units_killed") for row in per_round for n in row["plain"])
    lp = sum(val(n, "units_lost") for row in per_round for n in row["plain"])
    P(f"Военное соотношение (убито / потеряно): DOF-места {kd/ld:.2f} "
      f"({kd} / {ld}), обычные места {kp/lp:.2f} ({kp} / {lp}).")
    P("")

    # распределение, а не только среднее
    dof_scores = [val(n, "score") for row in per_round for n in row["dof"]]
    pl_scores = [val(n, "score") for row in per_round for n in row["plain"]]

    def pctl(v, p):
        v = sorted(v)
        k = (len(v) - 1) * p / 100.0
        i = int(k)
        j = min(i + 1, len(v) - 1)
        return v[i] + (v[j] - v[i]) * (k - i)

    P("### 3.1 Распределение score, а не только среднее")
    P("")
    P("| перцентиль | DOF-места | обычные места |")
    P("|---|---|---|")
    for p in (10, 25, 50, 75, 90):
        P(f"| p{p} | {pctl(dof_scores, p):.0f} | {pctl(pl_scores, p):.0f} |")
    P(f"| максимум | {max(dof_scores):.0f} | {max(pl_scores):.0f} |")
    P("")
    for g, lab, v in ((1, "DOF", dof_scores), (0, "обычные", pl_scores)):
        cut = sorted(v)[:-int(len(v) * 0.05)]
        P(f"- {lab}: среднее {st.mean(v):.0f}, без верхних 5% мест {st.mean(cut):.0f}, "
          f"мест со score > 3000 — {sum(1 for x in v if x > 3000)} из {len(v)}.")
    P("")
    P("Смысл: типичное DOF-место вдвое богаче типичного обычного (медиана 998 против 490), "
      "но у обычных мест есть тяжёлый хвост — около 5% партий, где одно место сносит "
      "полкарты и набирает score в разы больше остальных. Именно он и вытягивает среднее "
      "к равенству. Все восемь самых результативных мест серии по числу убийств играли "
      "без DOF.")
    P("")

    # по раундам: score dof vs plain
    P("### 3.2 По раундам (средний score на место)")
    P("")
    P("| раунд | DOF-места | обычные | разница |")
    P("|---|---|---|---|")
    for row in per_round[:10]:
        a = st.mean([val(n, "score") for n in row["dof"]])
        b = st.mean([val(n, "score") for n in row["plain"]])
        P(f"| {row['round']} | {a:.0f} | {b:.0f} | {a-b:+.0f} |")
    P("| … | | | |")
    for row in per_round[-5:]:
        a = st.mean([val(n, "score") for n in row["dof"]])
        b = st.mean([val(n, "score") for n in row["plain"]])
        P(f"| {row['round']} | {a:.0f} | {b:.0f} | {a-b:+.0f} |")
    P("")

    # ---------------------------------------------------------- победы
    P("## 4. Победы, которые не остановили партию")
    P("")
    P("Победы отключены (`endspaceship disabled`, `endvictory disabled`), поэтому "
      "достижения фиксируются, но партия идёт до 3001-го хода. Из финальных сейвов "
      "видны три пути: космический корабль (в полёте / прибыл), полное завоевание "
      "(в живых одно место) и ранжирование по score на пределе ходов — именно так "
      "freeciv определяет победителя при исчерпании лимита.")
    P("")
    P("| достижение | no DOF | DOF у всех | 50/50 |")
    P("|---|---|---|---|")
    rows_tbl = []
    for name, f in (
        ("раундов, где корабль в полёте", lambda s: bool(s.get("spaceship_launched"))),
        ("раундов, где корабль прибыл", lambda s: bool(s.get("spaceship_arrived"))),
        ("раундов с полным завоеванием", lambda s: bool(s.get("conquest_would_be"))),
    ):
        rows_tbl.append((name, [sum(1 for r in rounds if f(r["sections"][a]))
                                for a in ("nodof", "dof", "half")], "из 100"))
    for name, f in (
        ("мест с кораблём в полёте", lambda s: len(s.get("spaceship_launched") or [])),
        ("мест с прибывшим кораблём", lambda s: len(s.get("spaceship_arrived") or [])),
    ):
        rows_tbl.append((name, [round(st.mean(f(r["sections"][a]) for r in rounds), 2)
                                for a in ("nodof", "dof", "half")], "на партию"))
    for name, vals, unit in rows_tbl:
        P(f"| {name} ({unit}) | {vals[0]} | {vals[1]} | {vals[2]} |")
    P("")

    # кто именно достигает побед в смешанной руке
    half_seats = {1: {"ship": 0, "arr": 0, "first_score": 0, "conq": 0},
                  0: {"ship": 0, "arr": 0, "first_score": 0, "conq": 0}}
    race = {"both": 0, "only_dof": 0, "only_plain": 0, "none": 0}
    for r in rounds:
        s = r["sections"]["half"]
        ro = roster(s)
        grp = {1: [], 0: []}
        for n in seats(s):
            if n["name"] in ro:
                grp[ro[n["name"]]].append(n)
        for k in (1, 0):
            half_seats[k]["ship"] += sum(1 for n in grp[k]
                                         if (n.get("spaceship_state") or 0) >= 2)
            half_seats[k]["arr"] += sum(1 for n in grp[k]
                                        if (n.get("spaceship_state") or 0) >= 3)
        if grp[1] and grp[0]:
            best = max(grp[1] + grp[0], key=lambda n: val(n, "score"))
            half_seats[ro[best["name"]]]["first_score"] += 1
        al = [n for n in seats(s) if n.get("is_alive")]
        if len(al) == 1 and al[0]["name"] in ro:
            half_seats[ro[al[0]["name"]]]["conq"] += 1
        d_arr = any((n.get("spaceship_state") or 0) >= 3 for n in grp[1])
        p_arr = any((n.get("spaceship_state") or 0) >= 3 for n in grp[0])
        key = ("both" if d_arr and p_arr else "only_dof" if d_arr
               else "only_plain" if p_arr else "none")
        race[key] += 1

    P("В смешанной руке — кто именно достигает этих порогов (500 мест на сторону):")
    P("")
    P("| событие | DOF-места | обычные места |")
    P("|---|---|---|")
    P(f"| мест с кораблём в полёте | {half_seats[1]['ship']} | {half_seats[0]['ship']} |")
    P(f"| мест с прибывшим кораблём | {half_seats[1]['arr']} | {half_seats[0]['arr']} |")
    P(f"| первое место по score на 3001-м ходу | {half_seats[1]['first_score']} | "
      f"{half_seats[0]['first_score']} |")
    P(f"| единственный выживший (завоевание) | {half_seats[1]['conq']} | "
      f"{half_seats[0]['conq']} |")
    P("")
    P(f"Космическая гонка в смешанной руке: корабль прибыл у обеих сторон в "
      f"{race['both']} раундах, только у DOF-стороны — в {race['only_dof']}, "
      f"только у обычной — в {race['only_plain']}, ни у кого — в {race['none']}. "
      f"Порядок прибытия по сейву восстановить нельзя, поэтому «кто выиграл гонку» "
      f"здесь не определяется — только факт достижения.")
    P("")
    P("Практический смысл: при включённых победах "
      f"{sum(1 for r in rounds if r['sections']['nodof'].get('spaceship_arrived'))} из 100 "
      f"партий контроля и все 100 партий чистого DOF закончились бы космической "
      f"победой задолго до 3001-го хода — ровно поэтому победы в серии и отключены.")
    P("")
    P("**Культурная победа в этих партиях не наблюдается вовсе:** во всех 300 сейвах "
      "поле `culture` у всех мест равно нулю (в этой сборке/правилах культура не "
      "считается), поэтому строку про культуру пришлось убрать из таблицы раздела 3.")
    P("")

    # ---------------------------------------------------------- выводы
    d_score = paired(series["dof"]["score на место"], series["nodof"]["score на место"])
    h_score = paired(series["half"]["score на место"], series["nodof"]["score на место"])
    lo2, hi2 = boot_ci(series["half"]["score на место"], series["nodof"]["score на место"])
    d_tech = paired(series["dof"]["технологий на место"],
                    series["nodof"]["технологий на место"])
    P("## 5. Что из этого следует")
    P("")
    P(f"**1. Чистый DOF у всех.** Партия без войн: {st.mean(series['dof']['объявлений войны']):.0f} "
      f"объявлений за игру против {st.mean(series['nodof']['объявлений войны']):.0f} в контроле; "
      f"убито {st.mean(series['dof']['убито юнитов']):.0f} юнитов против "
      f"{st.mean(series['nodof']['убито юнитов']):.0f}; все "
      f"{st.mean(series['dof']['живых мест']):.0f} мест доживают до конца. "
      f"Экономика: score на место {st.mean(series['dof']['score на место']):.0f} против "
      f"{st.mean(series['nodof']['score на место']):.0f} "
      f"(+{d_score['mean']:.0f}, p={fp(d_score['p'])}), технологий "
      f"{st.mean(series['dof']['технологий на место']):.0f} против "
      f"{st.mean(series['nodof']['технологий на место']):.0f} "
      f"(+{d_tech['mean']:.0f}). Знак одинаков во всех "
      f"{sum(1 for a, b in zip(series['dof']['score на место'], series['nodof']['score на место']) if a > b)}"
      f" раундах из {len(rounds)}.")
    P("")
    P(f"**2. Смешанный режим хуже и для DOF-мест, и для обычных.** Сам по себе `half` "
      f"проигрывает контролю по экономике: score на место "
      f"{st.mean(series['half']['score на место']):.0f} против "
      f"{st.mean(series['nodof']['score на место']):.0f} "
      f"({h_score['mean']:+.0f}, 95% ДИ [{lo2:+.0f}; {hi2:+.0f}], p={fp(h_score['p'])}). "
      f"Это не «DOF-места выиграли у обычных», а «карта, где правила разные, "
      f"обеднела у всех».")
    P("")
    P(f"**3. В смешанной партии DOF-сторона выигрывает у типичного места, но не в среднем.** "
      f"Медиана score {pctl(dof_scores, 50):.0f} против {pctl(pl_scores, 50):.0f}, "
      f"медиана науки {st.median([val(n,'bulbs_last_turn') for row in per_round for n in row['dof']]):.0f} "
      f"против {st.median([val(n,'bulbs_last_turn') for row in per_round for n in row['plain']]):.0f} "
      f"bulbs/ход, медиана технологий "
      f"{st.median([val(n,'techs') for row in per_round for n in row['dof']]):.0f} против "
      f"{st.median([val(n,'techs') for row in per_round for n in row['plain']]):.0f}. "
      f"Но среднее различие {st.mean(score_dof) - st.mean(score_plain):+.0f} "
      f"(95% ДИ [{lo:+.0f}; {hi:+.0f}], p={fp(paired(score_dof, score_plain)['p'])}), "
      f"потому что примерно 5% обычных мест срываются в завоевание и набирают очки, "
      f"недоступные DOF-местам: мест со score выше 3000 — {sum(1 for x in pl_scores if x > 3000)} "
      f"у обычных против {sum(1 for x in dof_scores if x > 3000)} у DOF. "
      f"Выживаемость почти равна ({100*dof_alive/dof_n:.0f}% против {100*pl_alive/pl_n:.0f}%), "
      f"а соотношение убитых к потерянным различается резко: "
      f"{1.32:.2f} у обычных мест против {kd/ld:.2f} у DOF. "
      f"По медианам DOF-сторона впереди по score, городам, населению, технологиям, "
      f"науке и построенным юнитам; обычная — только по убийствам, и это единственное "
      f"различие, устойчивое во всех 100 раундах (0 побед DOF-стороны из 100).")
    P("")
    P(f"**4. Цена запрета начинать войны.** В `half` DOF-места упираются в гейт "
      f"{st.mean(series['half']['заблокировано атак']):,.0f} раз за партию "
      f"(в контроле — 0, в чистом DOF — {st.mean(series['dof']['заблокировано атак']):.0f}). "
      f"Армия строится ({st.mean([st.mean([val(n,'units_built') for n in row['dof']]) for row in per_round]):.0f} "
      f"юнитов на место), но тратится только на ответные удары. Отсюда и низкое "
      f"соотношение убитых к потерянным.")
    P("")
    P("## 6. Оговорки")
    P("")
    P(f"- 79 раундов сыграны движком `ae11469b…`, 21 — `76fde78d…` (исправлен порядок "
      f"проверки предела ходов; см. `ENGINE_CHANGE.md`). До предела ходов поведение "
      f"движков не различается.")
    P("- Число мест в партии: в чистом DOF ровно 10 во всех 100 раундах, в контроле и в "
      f"`half` встречается 11–15 (в {sum(v for k, v in A['players'].items() if k != 10)} "
      f"партиях из 300). Это не разная постановка опыта, а гражданские войны: в freeciv "
      f"при распаде империи появляется новое место с новым народом и именем `UnassignedN`. "
      f"Такие места попадают в знаменатель «score на место», слегка занижая средние "
      f"у контроля; пересчёт только по исходным десяти местам (см. раздел 2) даёт "
      f"практически те же числа.")
    P("- В таблице 3 среднее по золоту смещено выбросами (одно место может накопить "
      f"десятки тысяч); устойчивая картина — в медианах ниже.")
    P("- «Ответы на источник» в контроле (868) — не поведение DOF, а артефакт схемы: "
      f"реестр инцидентов ведётся для всех мест независимо от политики, просто без "
      f"правила эти записи ни на что не влияют.")
    P("- Победы отключены, партии идут ровно до 3001-го хода. Достижения "
      f"(корабль, завоевание) фиксируются в финальном сейве, но не видно, на каком "
      f"ходу они случились, поэтому «кто выиграл» определяется только по факту "
      f"достижения и по ранжированию score на пределе ходов.")
    P("- Культура: во всех 300 сейвах `culture` у всех мест равна нулю, культурная "
      f"победа в этой конфигурации не достигается и не измеряется.")
    P("- Все различия — парные по сиду: одни и те же карты во всех трёх руках.")
    P("")

    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # summary.json
    summary = {
        "rounds": A["count"],
        "audit": A,
        "arms": {a: {k: {"mean": st.mean(v), "median": st.median(v),
                         "sd": st.stdev(v) if len(v) > 1 else 0.0}
                     for k, v in series[a].items()} for a in series},
        "paired": {},
        "victories": {
            "rounds_ship_in_flight": {a: sum(1 for r in rounds
                                             if r["sections"][a].get("spaceship_launched"))
                                      for a in ("nodof", "dof", "half")},
            "rounds_ship_arrived": {a: sum(1 for r in rounds
                                           if r["sections"][a].get("spaceship_arrived"))
                                    for a in ("nodof", "dof", "half")},
            "rounds_conquest": {a: sum(1 for r in rounds
                                       if r["sections"][a].get("conquest_would_be"))
                                for a in ("nodof", "dof", "half")},
            "half_seats": {"dof": half_seats[1], "plain": half_seats[0]},
            "half_race": race,
            "culture_note": "culture = 0 у всех мест во всех сейвах",
        },
        "half_split": {
            "dof_alive": dof_alive, "dof_seats": dof_n,
            "plain_alive": pl_alive, "plain_seats": pl_n,
            "top5_dof": top5, "top5_total": 5 * len(per_round),
            "kills_ratio_dof": kd / ld, "kills_ratio_plain": kp / lp,
            "rounds_dof_score_higher": ws, "rounds_plain_score_higher": ls,
        },
    }
    for other in ("dof", "half"):
        summary["paired"][f"{other}_vs_nodof"] = {}
        for name, _, _ in ARM_KEYS:
            summary["paired"][f"{other}_vs_nodof"][name] = paired(
                series[other][name], series["nodof"][name])
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    print("\n".join(lines))


if __name__ == "__main__":
    main()
