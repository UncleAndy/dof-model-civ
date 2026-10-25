#!/usr/bin/env python3
"""Сводка серий run_series.py: три руки (классика / DOF / половина-наполовину).

Читает logs/series/<tag>.jsonl и печатает:
  * общий итог по руке — живые, уничтоженные игроки, уничтоженные и потерянные юниты;
  * итог по нациям — score, города, население, юниты, наука (технологии и bulbs/ход);
  * в смешанной руке отдельно места DOF и классические.

  series_report.py            # все три руки
  series_report.py --md out.md # ещё и markdown-отчёт
"""
import argparse
import json
import os
import statistics as st

ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(ROOT, "logs", "series")
ARMS = [("classic", "все классические"), ("dof", "все DOF"), ("mixed", "половина на половину")]
FIELDS = ["score", "ncities", "population_real", "nunits", "techs", "bulbs_last_turn",
          "science_rate", "units_killed", "units_lost", "gold"]


def load(tag):
    path = os.path.join(LOGS, f"{tag}.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get("failed"):
                rows.append(r)
    return sorted(rows, key=lambda r: r["game"])


def seat_kind(row, nation_name):
    """DOF место или классическое — по журналу состава (policy all/even/none)."""
    roster = row.get("dof_roster") or ""
    for item in roster.split(","):
        parts = item.split(":")
        if len(parts) == 3 and parts[0].strip() == nation_name:
            return "dof" if parts[2].strip().endswith("1") else "classic"
    return "classic" if row["policy"] == "none" else "dof" if row["policy"] == "all" else "?"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 1) if xs else 0.0


def arm_summary(tag, rows):
    if not rows:
        return None
    return {
        "tag": tag,
        "games": len(rows),
        "turns": rows[0]["turns"],
        "players": mean([r["players"] for r in rows]),
        "alive": mean([r["alive"] for r in rows]),
        "eliminated": mean([r["eliminated"] for r in rows]),
        "units_killed": mean([r["units_killed"] for r in rows]),
        "barb_killed": mean([r.get("barb_units_lost", 0) for r in rows]),
        "units_killed_regular": mean([r["units_killed"] - r.get("barb_units_lost", 0)
                                      for r in rows]),
        "units_lost_total": sum(r["units_lost"] for r in rows),
        "declares": sum(r["dof_declares"] for r in rows),
        "declares_dof": sum(r.get("dof_declares_dof_seats", 0) for r in rows),
        "attacks": sum(r.get("dof_news", 0) for r in rows),
        "blocked": sum(r["dof_blocked"] for r in rows),
        "suppressed": sum(r["dof_suppressed"] for r in rows),
        "secs": mean([r["secs"] for r in rows]),
    }


def nation_rows(rows):
    out = []
    for r in rows:
        for n in r["nations"]:
            if n.get("is_barbarian"):
                continue
            row = {"arm": r["tag"], "game": r["game"], "seat": seat_kind(r, n.get("name", "")),
                   "nation": n.get("nation"), "leader": n.get("name"),
                   "alive": n.get("is_alive")}
            for f in FIELDS:
                row[f] = n.get(f)
            out.append(row)
    return out


def agg(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    out = []
    for k, items in groups.items():
        row = {"group": k, "n": len(items)}
        for f in FIELDS:
            row[f] = mean([i.get(f) for i in items])
        row["alive_share"] = round(
            sum(1 for i in items if i["alive"]) / len(items), 2) if items else 0
        out.append(row)
    return sorted(out, key=lambda x: str(x["group"]))


def fmt_table(header, rows):
    widths = [max(len(str(header[i])), *(len(str(r[i])) for r in rows)) if rows else len(str(header[i]))
              for i in range(len(header))]
    line = "| " + " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(header)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    body = ["| " + " | ".join(str(r[i]).ljust(widths[i]) for i in range(len(header))) + " |"
            for r in rows]
    return "\n".join([line, sep] + body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=None, help="куда записать markdown-отчёт")
    ap.add_argument("--tags", default=None,
                    help="через запятую: classic,dof,mixed — какие руки сводить")
    args = ap.parse_args()
    global ARMS
    if args.tags:
        ARMS = [(t.strip(), t.strip()) for t in args.tags.split(",") if t.strip()]

    blocks = []
    for tag, title in ARMS:
        rows = load(tag)
        s = arm_summary(tag, rows)
        if not s:
            blocks.append(f"## {title} (`{tag}`)\n\nнет данных\n")
            continue
        summary = fmt_table(
            ["партий", "ходов", "игроков", "осталось", "уничтожено игроков",
             "убито варваров", "убито юнитов", "объявлений войны",
             "из них DOF-местами", "нападений"],
            [[s["games"], s["turns"], s["players"], s["alive"], s["eliminated"],
              round(s["barb_killed"], 1), round(s["units_killed_regular"], 1),
              s["declares"], s["declares_dof"], s["attacks"]]])
        nat = nation_rows(rows)
        if "mixed" in tag:
            agg_rows = agg(nat, lambda r: f"{r['seat']}")
            agg_hdr = ["места", "мест", "score", "города", "население", "юниты",
                       "технологии", "наука, bulbs/ход", "доля живых"]
            agg_table = fmt_table(agg_hdr, [[a["group"], a["n"], a["score"], a["ncities"],
                                             a["population_real"], a["nunits"], a["techs"],
                                             a["bulbs_last_turn"], a["alive_share"]]
                                            for a in agg_rows])
        else:
            agg_rows = agg(nat, lambda r: r["arm"])
            agg_hdr = ["рука", "мест", "score", "города", "население", "юниты",
                       "технологии", "наука, bulbs/ход", "доля живых"]
            agg_table = fmt_table(agg_hdr, [[a["group"], a["n"], a["score"], a["ncities"],
                                             a["population_real"], a["nunits"], a["techs"],
                                             a["bulbs_last_turn"], a["alive_share"]]
                                            for a in agg_rows])
        per_game = fmt_table(
            ["партия", "живых", "уничтожено", "убито варваров", "убито юнитов",
             "подавлено пар желания", "отказов от принуждения", "объявлений"],
            [[r["game"], f"{r['alive']}/{r['players']}", r["eliminated"],
              r.get("barb_units_lost", 0), r["units_killed"] - r.get("barb_units_lost", 0),
              r["dof_suppressed"], r["dof_blocked"], r["dof_declares"]] for r in rows])
        blocks.append(f"""## {title} (`{tag}`, policy={rows[0]['policy']})

{summary}

По нациям (среднее на место):

{agg_table}

По партиям:

{per_game}
""")

    # Полный отчёт по каждой нации в каждой партии — отдельным блоком,
    # потому что в чат такое не влезает, а вопрос был именно «по каждой нации».
    detail = ["\n## По каждой нации (полные таблицы)\n"]
    for tag, title in ARMS:
        rows = load(tag)
        if not rows:
            continue
        for r in rows:
            hdr = ["нация", "лидер", "место", "жив", "score", "города", "население",
                   "юниты", "технологии", "наука, bulbs/ход", "убито юнитов", "потеряно"]
            body = [[n.get("nation"), n.get("name"), seat_kind(r, n.get("name", "")),
                     "да" if n.get("is_alive") else "нет", n.get("score"), n.get("ncities"),
                     n.get("population_real"), n.get("nunits"), n.get("techs"),
                     n.get("bulbs_last_turn"), n.get("units_killed"), n.get("units_lost")]
                    for n in r["nations"] if not n.get("is_barbarian")]
            detail.append(f"\n**{title} — партия {r['game']}** (policy={r['policy']}, "
                          f"ходов {r['turns']}, убито юнитов {r['units_killed']}, "
                          f"нападений {r.get('dof_news', 0)})\n\n" + fmt_table(hdr, body))
    report = ("# Серии партий встроенного ИИ freeciv: классика / DOF / половина\n\n"
              + "\n".join(blocks) + "\n".join(detail))
    print(report)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(report)
        # машиночитаемая выгрузка: строка на нацию в партии
        import csv
        csv_path = os.path.splitext(args.md)[0] + ".csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["arm", "game", "seat", "nation", "leader",
                                              "alive"] + FIELDS)
            w.writeheader()
            for tag, _ in ARMS:
                for row in nation_rows(load(tag)):
                    w.writerow(row)
        print(f"\n[отчёт записан: {args.md}]")


if __name__ == "__main__":
    main()
