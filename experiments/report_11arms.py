#!/usr/bin/env python3
"""Финальный отчёт по серии 11 рук: 100 раундов × 11 партий × 3000 ходов.

Руки d0…d10 — доля мест, живущих по правилу DOF: 0/10 … 10/10.
В каждом раунде все 11 партий идут на одном сиде, поэтому:
  * срез «доза — эффект» показывает, что происходит со столом при росте доли;
  * срез «внутри игры» сравнивает DOF-места с обычными в одной партии;
  * срез «одно место, одна карта» сравнивает место с самим собой, когда
    правило включено и когда выключено (руки раунда вложены).
"""

import glob
import json
import math
import os
import random
import re
import statistics as st

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "dof-ab-11arms-100x3000")
ARMS = [f"d{i}" for i in range(11)]
ARM_DOF = {f"d{i}": i for i in range(11)}

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
    m, s = st.mean(d), sd(d)
    if s == 0:
        return 0.0, 1.0
    t = m / (s / math.sqrt(n))
    return t, 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))


def boot_ci(d, iters=4000, seed=11):
    if len(d) < 3:
        return None, None
    rnd = random.Random(seed)
    n = len(d)
    means = sorted(st.mean([d[rnd.randrange(n)] for _ in range(n)]) for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters) - 1]


def roster(sec):
    """{имя: (индекс, dof)} из строки росписи.

    Строка приходит в виде `[...]` (лог печатает список целиком), поэтому перед
    разбором снимаем скобки: иначе последнее место с `]` не разбирается и
    молча выпадает из сравнения.
    """
    raw = (sec.get("dof_roster") or "").strip()
    if raw.startswith("["):
        raw = raw[1:]
    if raw.endswith("]"):
        raw = raw[:-1]
    out = {}
    for part in raw.split(","):
        m = re.match(r"(.*):idx=(\d+):dof=([01])$", part.strip())
        if m:
            out[m.group(1).strip()] = (int(m.group(2)), int(m.group(3)))
    return out


def seats(sec):
    return [n for n in sec["nations"] if not n.get("is_barbarian")]


def load():
    rounds = []
    for p in sorted(glob.glob(os.path.join(OUT, "rounds", "round_*.json"))):
        with open(p, encoding="utf-8") as f:
            rounds.append(json.load(f))
    rounds.sort(key=lambda r: r["round"])
    return rounds


def observations(rounds):
    obs = []
    for r in rounds:
        for arm in ARMS:
            sec = r["sections"].get(arm)
            if not sec:
                continue
            ro = roster(sec)
            for n in seats(sec):
                key = n["name"].strip()
                if key not in ro:
                    continue
                idx, dof = ro[key]
                o = {"round": r["round"], "arm": arm, "idx": idx, "dof": dof,
                     "alive": bool(n.get("is_alive")), "ship": (n.get("spaceship_state") or 0)}
                for f, _, _ in SEAT_KEYS:
                    o[f] = val(n, f)
                obs.append(o)
    return obs


def main():
    rounds = load()
    obs = observations(rounds)
    lines = []

    def P(s=""):
        lines.append(s)

    nr = len(rounds)
    n_games = sum(1 for r in rounds for a in ARMS if a in r["sections"])
    dof_seats = [o for o in obs if o["dof"]]
    pl_seats = [o for o in obs if not o["dof"]]

    P(f"# 11 рук: {nr} раундов × 11 партий × 3000 ходов")
    P()
    P(f"Партий {n_games}, мест в сравнении {len(obs)} "
      f"({len(dof_seats)} с правилом DOF, {len(pl_seats)} без него).")
    P()

    # ------------------------------------------------------------ 1. аудит
    P("## 1. Аудит данных")
    P()
    eng = sorted({r["params"]["engine_md5"] for r in rounds})
    seeds = [r["seed"] for r in rounds]
    fts = sorted({s.get("final_turn") for r in rounds for s in r["sections"].values()})
    splinters = sum(len(seats(s)) - len(roster(s)) for r in rounds for s in r["sections"].values())
    P(f"- раундов {nr}, партий {n_games}, в каждом раунде по {len(ARMS)} рук")
    P(f"- сиды {min(seeds)}–{max(seeds)}; в 99 раундах это `200000 + 17·r`, "
      f"раунд 4 переигран на сиде 200069 (подробности — `SEED_NOTE.md`)")
    P(f"- движок: {', '.join('`' + e + '`' for e in eng)}")
    P(f"- финальные ходы: {fts[0]}–{fts[-1]} (победы отключены, партия всегда 3000 ходов)")
    P(f"- новых мест от гражданских войн (вне сравнения): {splinters}")

    want = {f"d{i}": i for i in range(11)}
    bad = []
    for r in rounds:
        for arm in ARMS:
            sec = r["sections"].get(arm)
            if not sec:
                bad.append((r["round"], arm, "нет раздела"))
                continue
            ents = re.findall(r":idx=(\d+):dof=([01])", sec.get("dof_roster") or "")
            dof_seats_here = sorted(int(i) for i, f in ents if f == "1")
            pol = sorted(int(x) for x in (sec.get("policy") or "").split(",") if x.strip().isdigit())
            if len(dof_seats_here) != want[arm] or len(ents) != 10:
                bad.append((r["round"], arm, "DOF-мест", len(dof_seats_here)))
            elif pol and dof_seats_here != pol:
                bad.append((r["round"], arm, "роспись != policy"))
    P(f"- политика применилась верно: в каждой партии ровно "
      f"0/1/…/10 мест с `dof=1`, роспись совпадает с `policy.conf`; "
      f"расхождений {len(bad)}")
    if bad:
        P(f"  - примеры: {bad[:5]}")
    P()

    # ------------------------------------------------- 2. кривая дозы
    P("## 2. Кривая «доза — эффект»: 0…10 мест из десяти")
    P()
    P("В ячейке — среднее / медиана на место. Среднее считается по раундам "
      "(сначала среднее по местам партии, потом по раундам), медиана — по всем "
      "местам выборки. В крайних руках вторая строка пуста по определению.")
    P()

    def sel(arm, kind):
        out = [o for o in obs if o["arm"] == arm]
        if kind == "dof":
            return [o for o in out if o["dof"]]
        if kind == "plain":
            return [o for o in out if not o["dof"]]
        return out

    def cell(kind, k, fmt):
        per_round = {}
        for o in kind:
            per_round.setdefault(o["round"], []).append(o[k])
        if not per_round:
            return "—"
        mean_over_rounds = st.mean(st.mean(v) for v in per_round.values())
        med = st.median([o[k] for o in kind])
        return f"{fmt.format(mean_over_rounds)} / {fmt.format(med)}"

    P("| метрика на место | сторона | " + " | ".join(ARMS) + " |")
    P("|" + "---|" * (len(ARMS) + 2))
    for k, label, fmt in SEAT_KEYS:
        for kind_name in ("DOF", "не-DOF"):
            kind = "dof" if kind_name == "DOF" else "plain"
            cells = [cell(sel(a, kind), k, fmt) for a in ARMS]
            P(f"| {label} | {kind_name} | " + " | ".join(cells) + " |")
    for kind_name in ("DOF", "не-DOF"):
        kind = "dof" if kind_name == "DOF" else "plain"
        P(f"| мест в выборке | {kind_name} | " +
          " | ".join(str(len(sel(a, kind))) for a in ARMS) + " |")
    P()

    # ------------------------------------------------- 3. внутри игры
    P("## 3. Внутри игры: DOF-места против обычных, по каждой руке")
    P()
    P("Для каждой руки и метрики: разница средних (DOF минус обычные) по раундам, "
      "в скобках — в скольких раундах DOF-группа выше, и p парного t-теста. "
      "В d0 и d10 сравнивать нечего: там только одна группа.")
    P()
    P("| метрика | " + " | ".join(f"d{i}" for i in range(1, 10)) + " |")
    P("|" + "---|" * 10)
    for k, label, fmt in (("score", "score", "{:.0f}"),
                          ("techs", "технологий", "{:.0f}"),
                          ("bulbs_last_turn", "наука", "{:.0f}"),
                          ("population_real", "население", "{:.0f}"),
                          ("ncities", "городов", "{:.1f}"),
                          ("units_killed", "убито", "{:.0f}"),
                          ("turns_alive", "ходов прожито", "{:.0f}")):
        cells = []
        for i in range(1, 10):
            arm = f"d{i}"
            a, b = [], []
            for r in rounds:
                sec = r["sections"].get(arm)
                if not sec:
                    continue
                ro = roster(sec)
                d, p_ = [], []
                for n in seats(sec):
                    key = n["name"].strip()
                    if key not in ro:
                        continue
                    (d if ro[key][1] else p_).append(val(n, k))
                if d and p_:
                    a.append(st.mean(d))
                    b.append(st.mean(p_))
            if not a:
                cells.append("—")
                continue
            _, pv, m = ttest(a, b)
            cells.append(f"{('+' if m >= 0 else '')}{fmt.format(m)} "
                         f"({sum(1 for x, y in zip(a, b) if x > y)}/{len(a)}); "
                         f"p={('%.2g' % pv) if pv is not None else '—'}")
        P(f"| {label} | " + " | ".join(cells) + " |")
    P()

    # ------------------------------------------------- 4. одно место, одна карта
    P("## 4. Одно и то же место на одной карте: правило включено против выключенного")
    P()
    P("Все руки раунда идут на одном сиде, поэтому место `i` получает ту же "
      "стартовую позицию. Для каждой пары (раунд, место) берутся его результаты "
      "в руках, где правило включено, и в руках, где выключено, и считается "
      "разница средних.")
    P()
    by_seat = {}
    for o in obs:
        by_seat.setdefault((o["round"], o["idx"]), []).append(o)

    P("| метрика | пар мест | DOF: среднее | без правила: среднее | разница | "
      "медиана разницы | DOF лучше | p (t) | 95% ДИ |")
    P("|---|---|---|---|---|---|---|---|---|")
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
        _, pv, m = ttest(a, b)
        diffs = [x - y for x, y in zip(a, b)]
        lo, hi = boot_ci(diffs)
        P(f"| {label} | {len(a)} | {fmt.format(st.mean(a))} | {fmt.format(st.mean(b))} | "
          f"{('+' if m >= 0 else '')}{fmt.format(m)} | {fmt.format(st.median(diffs))} | "
          f"{sum(1 for x in diffs if x > 0)}/{len(diffs)} | "
          f"{('%.2g' % pv) if pv is not None else '—'} | "
          f"[{fmt.format(lo)}; {fmt.format(hi)}] |")
    P()

    # шаг на одно место: d(k-1) против d(k), места, у которых правило включилось
    P("**Шаг на одно место.** Сравнение соседних рук: у места, которому добавили "
      "правило, берётся результат в `d(k-1)` и в `d(k)`. Это самый узкий шаг "
      "дозы — включение правила ровно у одного места из десяти.")
    P()
    P("| шаг | метрика | мест | средняя разница | медиана | лучше | p (t) |")
    P("|---|---|---|---|---|---|---|")
    idx_of = {}
    for o in obs:
        idx_of[(o["round"], o["arm"], o["idx"])] = o
    for k in range(1, 11):
        for key, label, fmt in (("score", "score", "{:.0f}"),
                                ("techs", "технологий", "{:.0f}"),
                                ("units_killed", "убито", "{:.0f}"),
                                ("turns_alive", "ходов прожито", "{:.0f}")):
            d = []
            for r in rounds:
                for idx in range(10):
                    hi = idx_of.get((r["round"], f"d{k}", idx))
                    lo = idx_of.get((r["round"], f"d{k-1}", idx))
                    if hi and lo and hi["dof"] and not lo["dof"]:
                        d.append(hi[key] - lo[key])
            if len(d) < 3:
                continue
            _, pv = onesample(d)
            m = st.mean(d)
            P(f"| d{k-1}→d{k} | {label} | {len(d)} | {('+' if m >= 0 else '')}"
              f"{fmt.format(m)} | {fmt.format(st.median(d))} | "
              f"{sum(1 for x in d if x > 0)}/{len(d)} | "
              f"{('%.2g' % pv) if pv is not None else '—'} |")
    P()

    # ------------------------------------------------- 5. механика
    P("## 5. Механика: кто кого бьёт (в среднем за партию)")
    P()
    P("Журнал хранит первые 40 объявлений и часть атак на партию — это выборка, "
      "но срез одинаковый для всех партий, поэтому колонки сравнимы.")
    P()

    def jstats(arm, side, what):
        vals = []
        for r in rounds:
            sec = r["sections"].get(arm)
            if not sec:
                continue
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

    P("| показатель | сторона | " + " | ".join(ARMS) + " |")
    P("|" + "---|" * (len(ARMS) + 2))
    for title, what in (("объявлений войны", "dec"), ("атак", "atk"),
                        ("атак против них", "vic")):
        for side, sname in ((1, "DOF"), (0, "не-DOF")):
            cells = []
            for a in ARMS:
                v = jstats(a, side, what)
                cells.append("—" if v is None else f"{v:.2f}")
            P(f"| {title} | {sname} | " + " | ".join(cells) + " |")
    P()
    P("| показатель | " + " | ".join(ARMS) + " |")
    P("|" + "---|" * (len(ARMS) + 1))
    for title, f in (("доля выживших мест, %",
                      lambda s: 100 * st.mean([1 if n.get("is_alive") else 0
                                               for n in seats(s) if n["name"] in roster(s)])),
                     ("объявлений войны (полный счёт)",
                      lambda s: (s.get("totals") or {}).get("declares", 0)),
                     ("заблокированных атак", lambda s: (s.get("journal") or {}).get("blocked", 0)),
                     ("нападений на источник", lambda s: (s.get("journal") or {}).get("on_source", 0)),
                     ("мест с кораблём в полёте", lambda s: len(s.get("spaceship_launched") or [])),
                     ("мест с прибывшим кораблём", lambda s: len(s.get("spaceship_arrived") or []))):
        cells = []
        for a in ARMS:
            vals = [f(r["sections"][a]) for r in rounds if a in r["sections"]]
            cells.append(f"{st.mean(vals):.2f}" if vals else "—")
        P(f"| {title} | " + " | ".join(cells) + " |")
    P()

    # ------------------------------------------------- 6. победы
    P("## 6. Достижения, которые не остановили партию")
    P()
    P("| событие | сторона | " + " | ".join(ARMS) + " |")
    P("|" + "---|" * (len(ARMS) + 2))
    for title, mode in (("мест с кораблём в полёте", "flight"),
                        ("мест с прибывшим кораблём", "arrived"),
                        ("партий, где сторона добила партию", "conq")):
        for side, sname in ((1, "DOF"), (0, "не-DOF")):
            cells = []
            for a in ARMS:
                vals = []
                for r in rounds:
                    sec = r["sections"].get(a)
                    if not sec:
                        continue
                    ro = roster(sec)
                    if mode == "conq":
                        al = [n for n in seats(sec) if n.get("is_alive") and n["name"].strip() in ro]
                        vals.append(1 if len(al) == 1 and ro[al[0]["name"].strip()][1] == side else 0)
                    else:
                        key = "spaceship_launched" if mode == "flight" else "spaceship_arrived"
                        vals.append(sum(1 for nm in (sec.get(key) or [])
                                        if ro.get(nm.strip(), (None, -1))[1] == side))
                cells.append(f"{st.mean(vals):.2f}" if vals else "—")
            P(f"| {title} | {sname} | " + " | ".join(cells) + " |")
    P()

    # ------------------------------------------------- 7. выводы
    P("## 7. Выводы")
    P()
    d0 = [o for o in obs if o["arm"] == "d0"]
    d10 = [o for o in obs if o["arm"] == "d10"]
    P(f"1. **Правило DOF переворачивает роли, а не «улучшает место».** "
      f"При доле 1–4 из 10 DOF-места отстают от соседей по score "
      f"({st.mean([o['score'] for o in obs if o['arm'] in ('d1','d2','d3','d4') and o['dof']]):.0f} "
      f"против "
      f"{st.mean([o['score'] for o in obs if o['arm'] in ('d1','d2','d3','d4') and not o['dof']]):.0f}), "
      f"при доле 6–10 — кратно превосходят.")
    P(f"2. **Стол реагирует нелинейно.** Полный отказ от DOF даёт "
      f"{st.mean([o['score'] for o in d0]):.0f} score на место, полное принятие — "
      f"{st.mean([o['score'] for o in d10]):.0f}; переход приходится на середину шкалы.")
    P(f"3. **Мирное место не воюет:** убито на место "
      f"{st.mean([o['units_killed'] for o in dof_seats]):.0f} у DOF против "
      f"{st.mean([o['units_killed'] for o in pl_seats]):.0f} у обычных.")
    P(f"4. **Космос достаётся DOF-стороне:** "
      f"{sum(1 for o in dof_seats if o['ship'] >= 3)} прибывших кораблей из "
      f"{len(dof_seats)} DOF-мест против {sum(1 for o in pl_seats if o['ship'] >= 3)} "
      f"из {len(pl_seats)} обычных.")
    P()
    P("## 8. Оговорки")
    P()
    P("- Раунд 4 переигран на сиде 200069 вместо 200068: на исходном сиде партия "
      "с правилом у одного места трижды не давала финального сейва. Внутри "
      "раунда сравнение корректно (все 11 рук на одной карте), межсерийные "
      "сопоставления по карте для этого раунда — нет.")
    P("- Руки раунда вложены (`d0 ⊂ d1 ⊂ … ⊂ d10`) и используют один сид: это "
      "даёт чистую дозу, но состав мест с правилом меняется от раунда к раунду "
      "по кругу, поэтому на 100 раундах он усредняется.")
    P("- Журнал режет выборку объявлений и атак: доли по нему — оценка, "
      "полный счёт есть только у объявлений.")
    P("- Золото у мирных мест — неиспользованный запас (ИИ не тратит казну без "
      "войны), и score его включает.")
    P("- Новые места от гражданских войн в сравнение не входят.")

    # валидация разметки таблиц
    bad_tables, block = [], []
    for ln in lines + [""]:
        if ln.startswith("|"):
            block.append(ln)
            continue
        if len(block) >= 2:
            h = block[0].count("|")
            s_ = block[1].count("|")
            wrong = [i + 3 for i, b in enumerate(block[2:]) if b.count("|") != h]
            if h != s_ or wrong:
                bad_tables.append((block[0][:50], h, s_, wrong[:3]))
        block = []
    if bad_tables:
        raise SystemExit("битые таблицы: " + repr(bad_tables))

    text = "\n".join(lines) + "\n"
    with open(os.path.join(OUT, "final_report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
