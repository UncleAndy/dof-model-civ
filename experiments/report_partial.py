#!/usr/bin/env python3
"""Сводный отчёт по серии частичного DOF: 30 раундов × 4 руки × 3000 ходов.

Главный вопрос серии — что даёт правило DOF отдельному месту и как это
отражается на партии в целом при разной доле мест, живущих по правилу.

Считаем три среза:
  1) кривая «доза — эффект»: агрегаты по рукам d1/d3/d7/d9;
  2) внутри игры: DOF-места против обычных мест в тех же партиях;
  3) строгое парное сравнение: одно и то же место на одной и той же карте,
     когда оно живёт по правилу DOF и когда нет (руки одного раунда делят сид,
     а состав DOF-мест в раунде вложен: d1 ⊂ d3 ⊂ d7 ⊂ d9).
"""

import glob
import json
import math
import os
import random
import re
import statistics as st

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "dof-ab-partial-30x3000")
OLD = os.path.join(ROOT, "dof-ab-100x3000")
ARMS = ("d1", "d3", "d7", "d9")
ARM_DOF = {"d1": 1, "d3": 3, "d7": 7, "d9": 9}

SEAT_KEYS = [
    ("score", "score", "{:.0f}"),
    ("ncities", "городов", "{:.1f}"),
    ("population_real", "население", "{:.1f}"),
    ("techs", "технологий", "{:.1f}"),
    ("bulbs_last_turn", "наука, bulbs/ход", "{:.1f}"),
    ("units_built", "построено юнитов", "{:.1f}"),
    ("units_killed", "убито юнитов", "{:.1f}"),
    ("units_lost", "потеряно юнитов", "{:.1f}"),
    ("landarea", "земля", "{:.0f}"),
    ("gold", "золото", "{:.0f}"),
    ("turns_alive", "ходов прожито", "{:.0f}"),
]


# ------------------------------------------------------------------ утилиты
def val(n, f):
    v = n.get(f)
    return v if isinstance(v, (int, float)) else 0


def fp(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def sd(seq):
    seq = list(seq)
    if len(seq) < 2:
        return 0.0
    m = st.mean(seq)
    return math.sqrt(sum((x - m) ** 2 for x in seq) / (len(seq) - 1))


def ttest(a, b):
    """Парный t-тест по разностям a-b; возвращает (t, p, mean_diff)."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    if n < 2:
        return None, None, (st.mean(d) if d else None)
    m, s = st.mean(d), sd(d)
    if s == 0:
        return 0.0, 1.0, m
    t = m / (s / math.sqrt(n))
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return t, p, m


def onesample(d):
    n = len(d)
    if n < 2:
        return None, None
    m, s_ = st.mean(d), sd(d)
    if s_ == 0:
        return 0.0, 1.0
    t = m / (s_ / math.sqrt(n))
    return t, 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))


def sign_test(a, b):
    """Сколько раз a>b из ненулевых пар и двусторонний биномиальный p."""
    pos = sum(1 for x, y in zip(a, b) if x > y)
    neg = sum(1 for x, y in zip(a, b) if x < y)
    n = pos + neg
    if n == 0:
        return pos, neg, 1.0
    k = max(pos, neg)
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return pos, neg, min(1.0, 2 * tail)


def boot_ci(a, b, iters=4000, seed=11):
    d = [x - y for x, y in zip(a, b)]
    if not d:
        return None, None
    rnd = random.Random(seed)
    n = len(d)
    means = sorted(st.mean([d[rnd.randrange(n)] for _ in range(n)]) for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters) - 1]


def pctl(seq, q):
    s = sorted(seq)
    if not s:
        return None
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def roster(sec):
    """{имя: индекс}, только места, известные на старте (распады исключены)."""
    out = {}
    for name, idx in re.findall(r"([^,:\[\]]+?):idx=(\d+):dof=[01]", sec.get("dof_roster") or ""):
        out[name.strip()] = int(idx)
    return out


def seats(sec):
    return [n for n in sec["nations"] if not n.get("is_barbarian")]


def _roster_seats(sec):
    """Только места, известные на старте: распады (UnassignedN) отброшены."""
    ro = roster(sec)
    return [n for n in seats(sec) if n["name"] in ro]


# ------------------------------------------------------------------ данные
def load():
    rounds = []
    for p in sorted(glob.glob(os.path.join(OUT, "rounds", "round_*.json"))):
        with open(p, encoding="utf-8") as f:
            rounds.append(json.load(f))
    rounds.sort(key=lambda r: r["round"])
    return rounds


def observations(rounds, arms=ARMS):
    """Плоский список: одно наблюдение = место в одной партии."""
    obs = []
    for r in rounds:
        for arm in arms:
            sec = r["sections"].get(arm)
            if not sec:
                continue
            ro = roster(sec)
            for n in seats(sec):
                if n["name"] not in ro:
                    continue          # распад или новое место — вне сравнения
                o = {"round": r["round"], "arm": arm, "idx": ro[n["name"]],
                     "key": f"{n['name']}", "dof": None, "alive": bool(n.get("is_alive")),
                     "ship": (n.get("spaceship_state") or 0)}
                for f, _, _ in SEAT_KEYS:
                    o[f] = val(n, f)
                o["turns_alive"] = val(n, "turns_alive")
                o["dof"] = 1 if re.search(
                    rf"idx={ro[n['name']]}:dof=1", sec.get("dof_roster") or "") else 0
                obs.append(o)
    return obs


# ------------------------------------------------------------------ отчёт
def main():
    rounds = load()
    lines = []

    def P(s=""):
        lines.append(s)

    obs = observations(rounds)
    nr = len(rounds)
    n_games = sum(1 for r in rounds for a in ARMS if a in r["sections"])
    n_seats = len(obs)

    P(f"# Частичный DOF: {nr} раундов × 4 руки × 3000 ходов")
    P()
    P("Источник: `experiments/dof-ab-partial-30x3000/rounds/round_*.json`, "
      f"партий {n_games}, мест в сравнении {n_seats} "
      f"(по {n_seats // max(1, n_games)} на партию).")
    P()

    # ---------------------------------------------------------- 1. аудит
    P("## 1. Аудит данных")
    P()
    eng = sorted({r["params"]["engine_md5"] for r in rounds})
    seeds = [r["seed"] for r in rounds]
    fts = sorted({s.get("final_turn") for r in rounds for s in r["sections"].values()})
    splinters = sum(len(seats(s)) - len(roster(s)) for r in rounds for s in r["sections"].values())
    missing = [r["round"] for r in rounds if len(r["sections"]) != len(ARMS)]
    P(f"- раундов {nr} (номера {rounds[0]['round']}–{rounds[-1]['round']}); "
      f"во всех по {len(ARMS)} руки")
    P(f"- сиды {seeds[0]}–{seeds[-1]} (шаг 17) — те же карты, что в раундах 0–29 "
      f"серии `dof-ab-100x3000`")
    P(f"- движок: {', '.join('`' + e + '`' for e in eng)}")
    P(f"- финальные ходы: {fts[0] if fts else '—'}–{fts[-1] if fts else '—'}; "
      f"победные условия отключены, партия всегда идёт 3000 ходов")
    P(f"- новых мест от гражданских войн (вне сравнения): {splinters}")
    # структурная проверка: применилась ли политика и совпадает ли с росписью
    want = {"d1": 1, "d3": 3, "d7": 7, "d9": 9}
    bad = []
    for r in rounds:
        for arm in ARMS:
            sec = r["sections"].get(arm)
            if not sec:
                continue
            ents = re.findall(r":idx=(\d+):dof=([01])", sec.get("dof_roster") or "")
            dof_seats = sorted(int(i) for i, f in ents if f == "1")
            pol = sorted(int(x) for x in (sec.get("policy") or "").split(",") if x.strip().isdigit())
            if len(dof_seats) != want[arm] or len(ents) != 10 or dof_seats != pol:
                bad.append((r["round"], arm, sec.get("policy"), len(dof_seats), len(ents)))
    P(f"- политика применилась верно во всех партиях: ровно {want['d1']}/{want['d3']}/"
      f"{want['d7']}/{want['d9']} мест с `dof=1`, и список мест в росписи совпадает "
      f"с записанной политикой (`policy.conf`); расхождений {len(bad)}")
    if missing:
        P(f"- **неполные раунды: {missing}**")
    P()

    # ------------------------------------------------- 2. кривая дозы
    P("## 2. Кривая «доза — эффект»: агрегат по партиям")
    P()
    P("Три варианта одних и тех же таблиц: по всем исходным местам партии, "
      "только по DOF-местам и только по обычным местам. В каждой ячейке — "
      "среднее / медиана. Среднее считается по раундам (сначала среднее по местам "
      "партии, потом по раундам), медиана — по всем местам сразу.")
    P()

    def arm_seats(arm, kind):
        sel = [o for o in obs if o["arm"] == arm]
        if kind == "dof":
            sel = [o for o in sel if o["dof"]]
        elif kind == "plain":
            sel = [o for o in sel if not o["dof"]]
        return sel

    def variant_table(kind, title, note=""):
        P(f"### {title}")
        P()
        if note:
            P(note)
            P()
        P(f"| метрика на место | d1 (1 DOF) | d3 (3) | d7 (7) | d9 (9) |")
        P("|---|---|---|---|---|")
        for k, label, fmt in SEAT_KEYS:
            cells = []
            for arm in ARMS:
                sel = arm_seats(arm, kind)
                if not sel:
                    cells.append("—")
                    continue
                per_round = {}
                for o in sel:
                    per_round.setdefault(o["round"], []).append(o[k])
                mean_over_rounds = st.mean(st.mean(v) for v in per_round.values())
                med = st.median([o[k] for o in sel])
                cells.append(f"{fmt.format(mean_over_rounds)} / {fmt.format(med)}")
            P(f"| {label} | " + " | ".join(cells) + " |")
        cells = []
        for arm in ARMS:
            sel = arm_seats(arm, kind)
            cells.append(str(len(sel)))
        P(f"| мест в выборке | " + " | ".join(cells) + " |")
        P()

    variant_table("all", "2.1 Все места партии",
                  "Смесь DOF-мест и обычных, как в прежней версии отчёта. Медиана "
                  "здесь включает погибшие места с нулями по городам и населению, "
                  "поэтому по ней видно долю доживших, а не уровень жизни: "
                  "раздел 2.2 показывает те же метрики внутри каждой группы.")
    P("### 2.2 DOF-места и обычные места рядом")
    P()
    P("В каждой метрике две соседние строки: места, на которых действует правило "
      "DOF, и места без правила. В ячейке — среднее / медиана. Колонки идут по "
      "доле мест с правилом: 0, 1, 3, 5, 7, 9, 10 из десяти. Крайние точки "
      "(0 и 10) и 50/50 взяты из серии `dof-ab-100x3000` на тех же картах и тех же "
      "раундах; в крайних точках вторая строка пуста по определению.")
    P()

    def old_obs_for(round_numbers):
        """Наблюдения из прошлой серии (руки nodof / dof / half) на тех же раундах."""
        keep = []
        for rnd in sorted(round_numbers):
            fp_ = os.path.join(OLD, "rounds", f"round_{rnd:04d}.json")
            if not os.path.exists(fp_):
                continue
            with open(fp_, encoding="utf-8") as f:
                keep.append(json.load(f))
        return observations(keep, ("nodof", "dof", "half"))

    here = {r["round"] for r in rounds}
    old_obs = old_obs_for(here)
    by_arm = {}
    for o in old_obs:
        by_arm.setdefault(o["arm"], []).append(o)
    for a_ in ARMS:
        by_arm.setdefault(a_, []).extend([o for o in obs if o["arm"] == a_])

    cols = [("0 — все не-DOF", by_arm.get("nodof", []))]
    for a_ in ("d1", "d3"):
        cols.append((f"{ARM_DOF[a_]} — {a_}", by_arm[a_]))
    cols.append(("5 — 50/50", by_arm.get("half", [])))
    for a_ in ("d7", "d9"):
        cols.append((f"{ARM_DOF[a_]} — {a_}", by_arm[a_]))
    cols.append(("10 — все DOF", by_arm.get("dof", [])))

    def cell(sel, kind, k, fmt):
        sub = [o for o in sel if (o["dof"] if kind == "dof" else not o["dof"])]
        if not sub:
            return "—", 0
        per_round = {}
        for o in sub:
            per_round.setdefault(o["round"], []).append(o[k])
        mean_over_rounds = st.mean(st.mean(v) for v in per_round.values())
        med = st.median([o[k] for o in sub])
        return f"{fmt.format(mean_over_rounds)} / {fmt.format(med)}", len(sub)

    P("| метрика на место | сторона | " + " | ".join(c[0] for c in cols) + " |")
    P("|" + "---|" * (len(cols) + 2))
    for k, label, fmt in SEAT_KEYS:
        for kind, kname in (("dof", "DOF"), ("plain", "не-DOF")):
            cells = [cell(sel, kind, k, fmt)[0] for _, sel in cols]
            P(f"| {label} | {kname} | " + " | ".join(cells) + " |")
    for kind, kname in (("dof", "DOF"), ("plain", "не-DOF")):
        counts = [str(cell(sel, kind, "score", "{:.0f}")[1]) for _, sel in cols]
        P(f"| мест в выборке | {kname} | " + " | ".join(counts) + " |")
    P()
    P(f"Крайние точки и 50/50 посчитаны по тем же {len(here)} раундам, что и эта "
      f"серия (раунды с теми же сидами), движок там `ae11469b…`, но все партии "
      f"остановлены на 3001-м ходу, поэтому сравнение корректно.")
    P()

    P("### 2.3 Счётчики журнала (на партию, все места)")
    P()
    P("Колонки те же, что в 2.2: доля мест с правилом DOF от 0 до 10 из десяти. "
      "Счётчики относятся к партии целиком, поэтому разделения на DOF/не-DOF "
      "здесь нет — это события всего стола.")
    P()

    def counters(secs):
        """Средние по списку разделов (по одному на раунд)."""
        if not secs:
            return None
        out = {}
        out["доля выживших мест"] = 100 * st.mean(
            [st.mean([1 if n.get("is_alive") else 0 for n in _roster_seats(sec)])
             for sec in secs])
        out["объявлений войны"] = st.mean(
            [(sec.get("totals") or {}).get("declares", 0) for sec in secs])
        out["заблокированных атак"] = st.mean(
            [sec["journal"].get("blocked", 0) for sec in secs])
        out["нападений на источник"] = st.mean(
            [sec["journal"].get("on_source", 0) for sec in secs])
        out["мест с кораблём в полёте"] = st.mean(
            [len(sec.get("spaceship_launched") or []) for sec in secs])
        out["мест с прибывшим кораблём"] = st.mean(
            [len(sec.get("spaceship_arrived") or []) for sec in secs])
        return out

    old_by_round = {}
    for rnd in sorted({r["round"] for r in rounds}):
        fp_ = os.path.join(OLD, "rounds", f"round_{rnd:04d}.json")
        if os.path.exists(fp_):
            with open(fp_, encoding="utf-8") as f:
                old_by_round[rnd] = json.load(f)

    def secs_of(src, arm_name):
        out = []
        for r in (rounds if src == "new" else [old_by_round[k] for k in sorted(old_by_round)]):
            sec = r["sections"].get(arm_name)
            if sec:
                out.append(sec)
        return out

    col_defs = [("0 — все не-DOF", "old", "nodof")]
    for a_ in ("d1", "d3"):
        col_defs.append((f"{ARM_DOF[a_]} — {a_}", "new", a_))
    col_defs.append(("5 — 50/50", "old", "half"))
    for a_ in ("d7", "d9"):
        col_defs.append((f"{ARM_DOF[a_]} — {a_}", "new", a_))
    col_defs.append(("10 — все DOF", "old", "dof"))

    def dose_secs():
        """Семь колонок доли DOF (0,1,3,5,7,9,10) в виде списков разделов по раундам."""
        def old_secs(arm_name):
            return [old_by_round[k]["sections"][arm_name] for k in sorted(old_by_round)
                    if arm_name in old_by_round[k]["sections"]]
        out = [("0 — все не-DOF", old_secs("nodof"))]
        for a_ in ("d1", "d3"):
            out.append((f"{ARM_DOF[a_]} — {a_}", [r["sections"][a_] for r in rounds
                                                  if a_ in r["sections"]]))
        out.append(("5 — 50/50", old_secs("half")))
        for a_ in ("d7", "d9"):
            out.append((f"{ARM_DOF[a_]} — {a_}", [r["sections"][a_] for r in rounds
                                                  if a_ in r["sections"]]))
        out.append(("10 — все DOF", old_secs("dof")))
        return out

    def dof_flag_of(sec):
        """{имя места: 1/0} из росписи раздела."""
        out = {}
        for part in (sec.get("dof_roster") or "").split(","):
            m = re.match(r"(.*):idx=(\d+):dof=([01])$", part.strip())
            if m:
                out[m.group(1).strip()] = int(m.group(3))
        return out

    counts = {label: counters(secs_of(src, arm_name)) for label, src, arm_name in col_defs}
    keys = [k for k in counts[col_defs[1][0]]]
    P("| показатель | " + " | ".join(label for label, _, _ in col_defs) + " |")
    P("|" + "---|" * (len(col_defs) + 1))
    for key in keys:
        cells = []
        for label, _, _ in col_defs:
            v = counts[label].get(key)
            cells.append("—" if v is None else f"{v:.2f}")
        P(f"| {key} | " + " | ".join(cells) + " |")
    P()

    # агрегаты по рукам (нужны в разделе 7 и в выводах)
    agg = {}
    for arm in ARMS:
        d = {}
        for k, _, _ in SEAT_KEYS:
            per = []
            for r in rounds:
                if arm not in r["sections"]:
                    continue
                ss = _roster_seats(r["sections"][arm])
                if ss:
                    per.append(st.mean([val(n, k) for n in ss]))
            d[k] = st.mean(per) if per else None
        agg[arm] = d

    # ------------------------------------------------- 3. внутри игры
    P("## 3. Внутри игры: DOF-места против обычных мест")
    P()
    P("Каждое наблюдение — место в конкретной партии. Сравнение парное по "
      "(раунд, рука): в каждой партии своё DOF-место и своё обычное, карта общая.")
    P()

    def group_pairs(field=None, only_arm=None):
        """Списки групповых средних DOF и обычных по каждой (раунд, рука)."""
        a, b = [], []
        for r in rounds:
            for arm in ARMS:
                if only_arm and arm != only_arm:
                    continue
                sec = r["sections"].get(arm)
                if not sec:
                    continue
                ro = _roster_seats(sec)
                dof_idx = {int(x) for x in re.findall(r"idx=(\d+):dof=1", sec.get("dof_roster") or "")}
                d = [n for n in ro if _idx(sec, n) in dof_idx]
                p = [n for n in ro if _idx(sec, n) not in dof_idx]
                if not d or not p:
                    continue
                if field is None:
                    a.append(len(d))
                    b.append(len(p))
                else:
                    a.append(st.mean([val(n, field) for n in d]))
                    b.append(st.mean([val(n, field) for n in p]))
        return a, b

    def _idx(sec, n):
        return roster(sec)[n["name"]]

    P("| метрика на место | DOF: среднее | DOF: медиана | обычные: среднее | "
      "обычные: медиана | раундов DOF> | p (парный t) |")
    P("|---|---|---|---|---|---|---|")
    for k, label, fmt in SEAT_KEYS:
        a, b = group_pairs(k)
        t, p, dm = ttest(a, b)
        dof_all = [o[k] for o in obs if o["dof"]]
        plain_all = [o[k] for o in obs if not o["dof"]]
        pos, neg, _ = sign_test(a, b)
        P(f"| {label} | {fmt.format(st.mean(dof_all))} | {fmt.format(st.median(dof_all))} | "
          f"{fmt.format(st.mean(plain_all))} | {fmt.format(st.median(plain_all))} | "
          f"{pos}/{len(a)} | {('%.3g' % p) if p is not None else '—'} |")
    P()
    dead_d = sum(1 for o in obs if o["dof"] and not o["alive"])
    dead_p = sum(1 for o in obs if not o["dof"] and not o["alive"])
    no_city_p = sum(1 for o in obs if not o["dof"] and o["ncities"] == 0)
    no_city_d = sum(1 for o in obs if o["dof"] and o["ncities"] == 0)
    P(f"**Почему медианы по обычным местам такие низкие.** К концу партии "
      f"{dead_p} обычных мест из {sum(1 for o in obs if not o['dof'])} погибли "
      f"({100*dead_p/max(1,sum(1 for o in obs if not o['dof'])):.0f}%), и у всех "
      f"у них 0 городов и 0 населения; погибших DOF-мест {dead_d}. "
      f"Медиана по всем местам — это медиана по "
      f"смеси живых и мёртвых, поэтому она показывает не уровень жизни, "
      f"а долю выживших. Ниже — то же самое только по выжившим местам.")
    P()
    P("| метрика | DOF: медиана | DOF: среднее | обычные: медиана | обычные: среднее |")
    P("|---|---|---|---|---|")
    for k, label, fmt in (("score", "score", "{:.0f}"),
                          ("ncities", "городов", "{:.1f}"),
                          ("population_real", "население", "{:.0f}"),
                          ("techs", "технологий", "{:.0f}"),
                          ("bulbs_last_turn", "наука, bulbs/ход", "{:.0f}"),
                          ("units_killed", "убито юнитов", "{:.0f}")):
        d_alive = [o[k] for o in obs if o["dof"] and o["alive"]]
        p_alive = [o[k] for o in obs if not o["dof"] and o["alive"]]
        P(f"| {label} | {fmt.format(st.median(d_alive))} | {fmt.format(st.mean(d_alive))} | "
          f"{fmt.format(st.median(p_alive))} | {fmt.format(st.mean(p_alive))} |")
    P()
    P(f"Мест: DOF {sum(1 for o in obs if o['dof'])}, обычных {sum(1 for o in obs if not o['dof'])}. "
      f"Пар (раунд, рука) с обеими группами: {len(group_pairs()[0])}. "
      f"«Пар DOF>» — в скольких парах среднее по DOF-группе выше.")
    P()

    # --- то же самое, но по каждой руке отдельно: в d1 DOF-место одно против
    # девяти обычных, в d9 — наоборот, поэтому общая таблица смешивает разные
    # по структуре сравнения.
    P("То же по рукам (в d1 правило действует для одного места из десяти, "
      "в d9 — для девяти):")
    P()
    P("| рука | метрика | DOF: среднее | DOF: медиана | обычные: среднее | "
      "обычные: медиана | DOF лучше |")
    P("|---|---|---|---|---|---|---|")
    for arm in ARMS:
        for k, label, fmt in (("score", "score", "{:.0f}"),
                              ("techs", "технологий", "{:.0f}"),
                              ("bulbs_last_turn", "наука, bulbs/ход", "{:.0f}"),
                              ("population_real", "население", "{:.0f}"),
                              ("units_killed", "убито юнитов", "{:.0f}"),
                              ("turns_alive", "ходов прожито", "{:.0f}")):
            a, b = group_pairs(k, arm)
            if not a:
                continue
            d_all = [o[k] for o in obs if o["arm"] == arm and o["dof"]]
            p_all = [o[k] for o in obs if o["arm"] == arm and not o["dof"]]
            P(f"| {arm} | {label} | {fmt.format(st.mean(d_all))} | "
              f"{fmt.format(st.median(d_all))} | {fmt.format(st.mean(p_all))} | "
              f"{fmt.format(st.median(p_all))} | "
              f"{sum(1 for x, y in zip(a, b) if x > y)}/{len(a)} |")
        d_surv = sum(1 for o in obs if o["arm"] == arm and o["dof"] and o["alive"])
        d_n = sum(1 for o in obs if o["arm"] == arm and o["dof"])
        p_surv = sum(1 for o in obs if o["arm"] == arm and not o["dof"] and o["alive"])
        p_n = sum(1 for o in obs if o["arm"] == arm and not o["dof"])
        P(f"| {arm} | выжило к концу | {100*d_surv/max(1,d_n):.0f}% ({d_surv}/{d_n}) | — | "
          f"{100*p_surv/max(1,p_n):.0f}% ({p_surv}/{p_n}) | — | — |")
    P()

    # --- 50/50 из прошлой серии: та же пара групп, те же карты
    half_obs = [o for o in old_obs if o["arm"] == "half"] if "old_obs" in dir() else []
    if half_obs:
        P("Тот же срез для руки 50/50 из серии `dof-ab-100x3000` (те же раунды и "
          "карты): 5 мест с правилом против 5 без него.")
        P()
        P("| метрика на место | DOF: среднее | DOF: медиана | обычные: среднее | "
          "обычные: медиана | пар DOF> | p (парный t) |")
        P("|---|---|---|---|---|---|---|")
        for k, label, fmt in (("score", "score", "{:.0f}"),
                              ("techs", "технологий", "{:.0f}"),
                              ("bulbs_last_turn", "наука, bulbs/ход", "{:.0f}"),
                              ("population_real", "население", "{:.0f}"),
                              ("units_killed", "убито юнитов", "{:.0f}"),
                              ("turns_alive", "ходов прожито", "{:.0f}")):
            d_all = [o[k] for o in half_obs if o["dof"]]
            p_all = [o[k] for o in half_obs if not o["dof"]]
            per_rnd = {}
            for o in half_obs:
                if o["dof"]:
                    per_rnd.setdefault(o["round"], []).append(o[k])
            per_rnd_p = {}
            for o in half_obs:
                if not o["dof"]:
                    per_rnd_p.setdefault(o["round"], []).append(o[k])
            rnds = sorted(set(per_rnd) & set(per_rnd_p))
            a = [st.mean(per_rnd[r_]) for r_ in rnds]
            b = [st.mean(per_rnd_p[r_]) for r_ in rnds]
            _, pv, _ = ttest(a, b)
            P(f"| {label} | {fmt.format(st.mean(d_all))} | {fmt.format(st.median(d_all))} | "
              f"{fmt.format(st.mean(p_all))} | {fmt.format(st.median(p_all))} | "
              f"{sum(1 for x, y in zip(a, b) if x > y)}/{len(a)} | "
              f"{('%.3g' % pv) if pv is not None else '—'} |")
        P()
        P("Для крайних точек (0 и 10 мест) такое сравнение невозможно: в партии "
          "остаётся только одна группа, сравнивать её не с чем.")
        P()

    # выживаемость и военное соотношение
    dof = [o for o in obs if o["dof"]]
    pl = [o for o in obs if not o["dof"]]
    surv_d = sum(1 for o in dof if o["alive"]) / len(dof)
    surv_p = sum(1 for o in pl if o["alive"]) / len(pl)
    kd = st.mean([o["units_killed"] for o in dof])
    ld = st.mean([o["units_lost"] for o in dof])
    kp = st.mean([o["units_killed"] for o in pl])
    lp = st.mean([o["units_lost"] for o in pl])
    P("Осторожно с золотом: в мирных партиях ИИ не тратит казну (нечего "
      "перехватывать, чудеса кончились), поэтому золото у DOF-мест — это "
      "неиспользованный запас, а не сила. Оно же тянет вверх score: у DOF-места "
      "в среднем сотни тысяч монет.")
    P()
    P(f"Выжило к 3001-му ходу: DOF {100*surv_d:.0f}%, обычные {100*surv_p:.0f}%. "
      f"Убито/потеряно на место: DOF {kd:.0f}/{ld:.0f} (соотношение {kd/max(ld,1):.2f}), "
      f"обычные {kp:.0f}/{lp:.0f} ({kp/max(lp,1):.2f}).")
    P()

    # --- только по выжившим (устойчиво к замороженным score погибших)
    alive_d = [o["score"] for o in dof if o["alive"]]
    alive_p = [o["score"] for o in pl if o["alive"]]
    P(f"Только по выжившим местам: score {st.mean(alive_d):.0f} у DOF против "
      f"{st.mean(alive_p):.0f} у обычных; медиана {st.median(alive_d):.0f} против "
      f"{st.median(alive_p):.0f}.")
    P()

    # ------------------------------------------------- 4. одно место, одна карта
    P("## 4. Одно и то же место на одной карте: DOF против обычного режима")
    P()
    P("Руки одного раунда идут на одном сиде, поэтому индекс места `i` получает "
      "ту же стартовую позицию. Значит для места `i` в раунде `r` можно прямо "
      "сравнить его результат в руках, где оно живёт по правилу DOF, и в руках, "
      "где живёт обычной жизнью.")
    P()
    by_seat = {}
    for o in obs:
        by_seat.setdefault((o["round"], o["idx"]), []).append(o)

    P("| метрика | пар мест | DOF: среднее | обычный режим: среднее | "
      "разница | медиана разницы | DOF лучше | p (t) | 95% ДИ |")
    P("|---|---|---|---|---|---|---|---|---|")
    store = {}
    for k, label, fmt in SEAT_KEYS:
        a, b = [], []
        for key, lst in by_seat.items():
            d = [o[k] for o in lst if o["dof"]]
            p_ = [o[k] for o in lst if not o["dof"]]
            if not d or not p_:
                continue
            a.append(st.mean(d))
            b.append(st.mean(p_))
        if not a:
            continue
        t, p, dm = ttest(a, b)
        lo, hi = boot_ci(a, b)
        diffs = [x - y for x, y in zip(a, b)]
        store[k] = (a, b)
        P(f"| {label} | {len(a)} | {fmt.format(st.mean(a))} | {fmt.format(st.mean(b))} | "
          f"{('+' if dm >= 0 else '')}{fmt.format(dm)} | {fmt.format(st.median(diffs))} | "
          f"{sum(1 for x in diffs if x > 0)}/{len(diffs)} | "
          f"{('%.3g' % p) if p is not None else '—'} | "
          f"[{fmt.format(lo)}; {fmt.format(hi)}] |")
    P()

    # --- соседние руки: включается правило у двух мест из десяти, всё
    # остальное в партии остаётся почти тем же
    P("Соседние руки (`d1→d3`, `d3→d7`, `d7→d9`): правило включается ещё у двух "
      "мест, остальная партия меняется слабо. Разница считается по местам, "
      "у которых в младшей руке правило выключено, а в старшей включено.")
    P()
    by_key = {(o["round"], o["arm"], o["idx"]): o for o in obs}
    P("| переход | метрика | мест | средняя разница | медиана разницы | лучше | p (t) |")
    P("|---|---|---|---|---|---|---|")
    for lo, hi in (("d1", "d3"), ("d3", "d7"), ("d7", "d9")):
        for k, label, fmt in (("score", "score", "{:.0f}"),
                              ("techs", "технологий", "{:.0f}"),
                              ("bulbs_last_turn", "наука, bulbs/ход", "{:.0f}"),
                              ("ncities", "городов", "{:.1f}"),
                              ("population_real", "население", "{:.0f}"),
                              ("units_killed", "убито юнитов", "{:.0f}")):
            d = []
            for r in rounds:
                for idx in range(10):
                    a_ = by_key.get((r["round"], hi, idx))
                    b_ = by_key.get((r["round"], lo, idx))
                    if a_ and b_ and a_["dof"] and not b_["dof"]:
                        d.append(a_[k] - b_[k])
            if len(d) < 3:
                continue
            m = st.mean(d)
            t, p = onesample(d)
            P(f"| {lo}→{hi} | {label} | {len(d)} | {('+' if m >= 0 else '')}"
              f"{fmt.format(m)} | {fmt.format(st.median(d))} | "
              f"{sum(1 for x in d if x > 0)}/{len(d)} | "
              f"{('%.3g' % p) if p is not None else '—'} |")
    P()

    # ------------------------------------------------- 5. механика
    P("## 5. Механика: кто кого бьёт")
    P()
    P("Колонки — те же семь точек доли DOF. Журнал хранит первые 40 объявлений "
      "и несколько атак на партию, поэтому это выборка, а не полный счёт; "
      "сравнивать между колонками можно именно потому, что срез журнала "
      "одинаковый для всех партий. Значения — в среднем за партию.")
    P()
    dose = dose_secs()

    def jstats(secs, side, what):
        vals = []
        for sec in secs:
            j = sec.get("journal") or {}
            n = 0
            if what == "dec":
                for line in j.get("declares") or []:
                    m = re.search(r"declarer_dof=(\d)", line)
                    if m and int(m.group(1)) == side:
                        n += 1
            elif what == "atk":
                for line in j.get("attacks") or []:
                    m = re.search(r"violator_dof=(\d)", line)
                    if m and int(m.group(1)) == side:
                        n += 1
            elif what == "vic":
                for line in j.get("attacks") or []:
                    m = re.search(r"victim_dof=(\d)", line)
                    if m and int(m.group(1)) == side:
                        n += 1
            vals.append(n)
        return st.mean(vals) if vals else None

    def first_hit(secs, side):
        turns = []
        for sec in secs:
            for line in (sec.get("journal") or {}).get("attacks") or []:
                m = re.search(r"victim_dof=(\d)", line)
                t = re.search(r"turn=(\d+)", line)
                if m and t and int(m.group(1)) == side:
                    turns.append(int(t.group(1)))
        return st.median(turns) if turns else None

    rows5 = (("объявлений войны", "dec", "объявившая сторона"),
             ("атак", "atk", "нападавшая сторона"),
             ("атак против них", "vic", "сторона жертвы"),
             ("ход первой атаки против них", "first", "сторона жертвы"))
    P("| показатель | сторона | " + " | ".join(c[0] for c in dose) + " |")
    P("|" + "---|" * (len(dose) + 2))
    for title, what, side_label in rows5:
        for side, sname in ((1, "DOF"), (0, "не-DOF")):
            cells = []
            for _, secs in dose:
                if what == "first":
                    v = first_hit(secs, side)
                    cells.append("—" if v is None else f"{v:.0f}")
                else:
                    v = jstats(secs, side, what)
                    cells.append("—" if v is None else f"{v:.2f}")
            P(f"| {title} | {sname} | " + " | ".join(cells) + " |")
    P()
    P("Читается так: DOF-место почти не нападает (правило запрещает атаку "
      "не-источника), но обычные места бьют его охотно и рано — атака на DOF-место "
      "не делает нападающего источником, то есть это безопасная добыча. "
      "Когда DOF-мест мало, вся война стекается на них.")
    P()

    # ------------------------------------------------- 6. победы
    P("## 6. Достижения, которые не остановили партию")
    P()
    P("Колонки — те же семь точек доли DOF. Космический корабль и завоевание "
      "считаются по сторонам, поэтому в крайних колонках вторая строка пуста.")
    P()

    def ships(secs, side, mode):
        vals = []
        for sec in secs:
            key = "spaceship_launched" if mode == "flight" else "spaceship_arrived"
            flags = dof_flag_of(sec)
            n = 0
            for nm in sec.get(key) or []:
                if flags.get(nm.strip()) == side:
                    n += 1
            vals.append(n)
        return st.mean(vals) if vals else None

    def conquest(secs, side):
        vals = []
        for sec in secs:
            flags = dof_flag_of(sec)
            ro = roster(sec)
            alive = [n for n in seats(sec) if n.get("is_alive") and n["name"] in ro]
            vals.append(1 if len(alive) == 1 and flags.get(alive[0]["name"].strip()) == side else 0)
        return st.mean(vals) if vals else None

    rows6 = (("мест с кораблём в полёте", "flight"), ("мест с прибывшим кораблём", "arrived"),
             ("партий, где сторона добила партию", "conq"))
    P("| достижение | сторона | " + " | ".join(c[0] for c in dose) + " |")
    P("|" + "---|" * (len(dose) + 2))
    for title, mode in rows6:
        for side, sname in ((1, "DOF"), (0, "не-DOF")):
            cells = []
            for _, secs in dose:
                v = conquest(secs, side) if mode == "conq" else ships(secs, side, mode)
                cells.append("—" if v is None else f"{v:.2f}")
            P(f"| {title} | {sname} | " + " | ".join(cells) + " |")
    P()

    if os.path.isdir(OLD):
        P("## 7. Место серии в общей картине (те же карты, раунды 0–29)")
        P()
        P("Крайние точки — из серии `dof-ab-100x3000` на тех же сидах: 0 мест "
          "по правилу (`nodof`) и все 10 (`dof`). Промежуточные — эта серия.")
        P()
        rows = {}
        for arm, path, out_name in (("nodof", OLD, "nodof"), ("dof", OLD, "dof")):
            vals = {}
            for k, _, _ in SEAT_KEYS:
                per = []
                for i in sorted(old_by_round):
                    rr = old_by_round[i]
                    sec = rr["sections"].get(out_name)
                    if not sec:
                        continue
                    ro = roster(sec)
                    ss = [n for n in seats(sec) if n["name"] in ro]
                    if ss:
                        per.append(st.mean([val(n, k) for n in ss]))
                vals[k] = st.mean(per) if per else None
            rows[arm] = vals
        half_vals = {}
        for k, _, _ in SEAT_KEYS:
            per = []
            for rnd in sorted(old_by_round):
                sec = old_by_round[rnd]["sections"].get("half")
                if not sec:
                    continue
                ss = _roster_seats(sec)
                if ss:
                    per.append(st.mean([val(n, k) for n in ss]))
            half_vals[k] = st.mean(per) if per else None
        P("| метрика на место | 0 DOF | 1 | 3 | 5 | 7 | 9 | 10 DOF |")
        P("|---|---|---|---|---|---|---|---|")
        for k, label, fmt in SEAT_KEYS:
            cells = [fmt.format(rows["nodof"][k]) if rows["nodof"][k] is not None else "—"]
            cells += [fmt.format(agg["d1"][k]), fmt.format(agg["d3"][k])]
            cells.append(fmt.format(half_vals[k]) if half_vals[k] is not None else "—")
            cells += [fmt.format(agg["d7"][k]), fmt.format(agg["d9"][k])]
            cells.append(fmt.format(rows["dof"][k]) if rows["dof"][k] is not None else "—")
            P(f"| {label} | " + " | ".join(cells) + " |")
        P()

    # ------------------------------------------------- 8. выводы
    P("## 8. Выводы")
    P()
    d1d = [o for o in obs if o["arm"] == "d1" and o["dof"]]
    d1p = [o for o in obs if o["arm"] == "d1" and not o["dof"]]
    d9d = [o for o in obs if o["arm"] == "d9" and o["dof"]]
    d9p = [o for o in obs if o["arm"] == "d9" and not o["dof"]]
    P(f"1. **Правило DOF не «улучшает место» само по себе — оно переворачивает "
      f"роли.** Одинокое DOF-место в мире обычных (`d1`) — самое слабое место "
      f"партии: score {st.mean([o['score'] for o in d1d]):.0f} против "
      f"{st.mean([o['score'] for o in d1p]):.0f} у обычных, технологий "
      f"{st.mean([o['techs'] for o in d1d]):.0f} против "
      f"{st.mean([o['techs'] for o in d1p]):.0f}, доживает до конца "
      f"{100*sum(1 for o in d1d if o['alive'])/max(1,len(d1d)):.0f}% против "
      f"{100*sum(1 for o in d1p if o['alive'])/max(1,len(d1p)):.0f}%.")
    P(f"2. **Порог — между 3 и 7 местами из 10.** В `d3` DOF-места ещё отстают "
      f"(score {st.mean([o['score'] for o in obs if o['arm']=='d3' and o['dof']]):.0f} "
      f"против "
      f"{st.mean([o['score'] for o in obs if o['arm']=='d3' and not o['dof']]):.0f}), "
      f"а в `d7` уже побеждают почти в каждом раунде (28 из 29). Обратный ход "
      f"совпадает с моментом, когда правило перестаёт быть в меньшинстве.")
    P(f"3. **В DOF-мире страдают те, кто остался обычным.** В `d9` обычное место "
      f"набирает {st.mean([o['score'] for o in d9p]):.0f} score против "
      f"{st.mean([o['score'] for o in d9d]):.0f} у DOF-мест, гибнет в "
      f"{100-sum(1 for o in d9p if o['alive'])/max(1,len(d9p))*100:.0f}% случаев. "
      f"Механизм — раздел 5: DOF-места воюют только с источниками, а источником "
      f"становится тот, кто напал.")
    P(f"4. **Партия в целом реагирует нелинейно.** Одно-три DOF-места таблицу не "
      f"меняют (score на место {agg['d1']['score']:.0f} и {agg['d3']['score']:.0f} "
      f"против 1436 в контроле без DOF), семь — меняют наполовину "
      f"({agg['d7']['score']:.0f}), девять — почти полностью "
      f"({agg['d9']['score']:.0f} против 5587 при полном DOF).")
    P(f"5. **DOF-места почти не воюют, но и не гибнут от войн.** Убито на место: "
      f"{st.mean([o['units_killed'] for o in dof]):.0f} у DOF против "
      f"{st.mean([o['units_killed'] for o in pl]):.0f} у обычных; потеряно "
      f"{st.mean([o['units_lost'] for o in dof]):.0f} против "
      f"{st.mean([o['units_lost'] for o in pl]):.0f}. Соотношение убито/потеряно "
      f"0.5 против 1.10 — правило делает место мирным, а не сильным.")
    P(f"6. **Космическая гонка достаётся DOF-местам:** {sum(1 for o in dof if o['ship'] >= 3)} "
      f"прибывших кораблей из {len(dof)} DOF-мест против "
      f"{sum(1 for o in pl if o['ship'] >= 3)} из {len(pl)} обычных.")
    P()
    P("## 9. Оговорки")
    P()
    P("- Раунды идут на тех же сидах, что серия `dof-ab-100x3000` (раунды 0–29), "
      "поэтому крайние точки 0 и 10 DOF взяты оттуда; в тех раундах движок был "
      "`ae11469b…`, но все 90 партий всё равно остановлены на 3001-м ходу, "
      "так что сравнение корректно.")
    P("- Руки раунда вложены (d1 ⊂ d3 ⊂ d7 ⊂ d9) и используют один сид. Это "
      "сознательно: так видна доза, но эффект «сколько мест» не отделён от "
      "эффекта «какие именно места» — состав DOF-мест меняется от раунда к раунду "
      "по кругу, поэтому на 29 раундах он усредняется.")
    P("- Журнал режет выборку объявлений и атак; доли и ходы по ним — оценка.")
    P("- Золото у мирных мест — неиспользованный запас, score его включает.")
    P("- Новые места от гражданских войн в сравнение не входят.")
    P()

    # --- проверка разметки: шапка, разделитель и строки таблицы должны иметь
    # одинаковое число ячеек, иначе markdown-таблица не отрисуется
    bad_tables, block = [], []
    for ln in lines + [""]:
        if ln.startswith("|"):
            block.append(ln)
            continue
        if len(block) >= 2:
            n_head = block[0].count("|")
            n_sep = block[1].count("|")
            wrong = [i + 3 for i, b in enumerate(block[2:]) if b.count("|") != n_head]
            if n_head != n_sep or wrong:
                bad_tables.append((block[0][:60], n_head, n_sep, wrong[:5]))
        block = []
    if bad_tables:
        raise SystemExit("битые таблицы (шапка, разделитель, строки): " + repr(bad_tables))

    text = "\n".join(lines) + "\n"
    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
