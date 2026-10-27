#!/usr/bin/env python3
"""Разбор гибели мест в контрольном плече (--policy none).

Для каждого раунда, где в JSON отмечен погибший игрок, партия переигрывается
на том же сиде (движок детерминирован), сохраняется финальный сейв и журнал.
Из сейва берутся основанные погибшим города и их текущие владельцы, из журнала —
объявления войны и нападения на погибшего. Результат: deaths.json + таблица.

  deaths.py --limit 20
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = os.path.join(ROOT, "experiments", "dof-ab-26102026")
LOGS = os.path.join(ROOT, "deploy", "freeciv-dof", "logs", "series")
RUN = os.path.join(ROOT, "deploy", "freeciv-dof", "run_series.py")
PY = os.path.join(ROOT, ".venv", "bin", "python")
CONTAINER = "freeciv-web"
RUNDIR = "/home/docker/dofrun/series"
SAVES = os.path.join(EXP, "death_saves")


def sh(cmd, timeout=900):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def dead_rounds():
    out = []
    for p in sorted(glob.glob(os.path.join(EXP, "rounds", "round_*.json"))):
        r = json.load(open(p, encoding="utf-8"))
        s = r["sections"]["nodof"]
        dead = [n for n in s["nations"]
                if not n.get("is_alive") and n.get("nation") not in ("Barbarian", "Pirate")]
        if dead:
            out.append((r["round"], s["seed"], dead, s))
    return out


def parse_save(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    blocks = re.split(r"^\[(player|score)(\d+)\]\s*$", txt, flags=re.M)
    players = {}
    for i in range(1, len(blocks), 3):
        if blocks[i] != "player":
            continue
        players[int(blocks[i + 1])] = blocks[i + 2]

    def fld(b, k):
        m = re.search(rf"^{re.escape(k)}=(.*)$", b, flags=re.M)
        return m.group(1).strip() if m else None

    out = {}
    for pid, b in players.items():
        name = (fld(b, "name") or "").strip('"')
        nation = (fld(b, "nation") or "").strip('"')
        alive = fld(b, "is_alive") == "TRUE"
        cities = []
        m = re.search(r"^c=\{(.*)$", b, flags=re.M)
        if m:
            keys = [k.strip().strip('"') for k in m.group(1).rstrip("}").split(",")]
            rest = b[m.end():].splitlines()
            for line in rest:
                line = line.strip()
                if line == "}":
                    break
                if not line:
                    continue
                vals = re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", line)
                row = dict(zip(keys, vals))
                cities.append({"name": (row.get("name") or "").strip('"'),
                               "original": row.get("original"),
                               "size": row.get("size")})
        out[pid] = {"name": name, "nation": nation, "alive": alive, "cities": cities}
    return out


def analyse_journal(text, dead_name):
    declares, attacks = [], []
    last_turn = None
    for line in text.splitlines():
        if "[DOF] declare" in line and dead_name in line:
            m = re.search(r"turn=(\d+) declarer=(.*?) target=(.*?) ", line)
            if m:
                declares.append({"turn": int(m.group(1)), "declarer": m.group(2),
                                 "target": m.group(3)})
        elif "[DOF] unit_source" in line and f"victim={dead_name}" in line:
            m = re.search(r"turn=(\d+) unit=(\d+) utype=(\S+) owner=(.*?) victim=", line)
            if m:
                attacks.append({"turn": int(m.group(1)), "owner": m.group(4),
                                "utype": m.group(3), "unit": m.group(2)})
        if dead_name in line:
            t = re.search(r"turn=(\d+)", line)
            if t:
                last_turn = max(last_turn or 0, int(t.group(1)))
    return declares, attacks, last_turn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(SAVES, exist_ok=True)
    rows = dead_rounds()
    if args.limit:
        rows = rows[:args.limit]
    result = []
    for rnd, seed, dead, sec in rows:
        tag = f"death{rnd:03d}"
        save_host = os.path.join(SAVES, f"{tag}.sav")
        if not os.path.exists(save_host):
            jsonl = os.path.join(LOGS, f"{tag}.jsonl")
            if os.path.exists(jsonl):
                os.remove(jsonl)
            sh(f"docker exec {CONTAINER} sh -lc 'rm -rf {RUNDIR}/{tag}'")
            cmd = (f"{PY} {RUN} --tag {tag} --games 1 --turns 200 --aifill 10 --size 2 "
                   f"--par 1 --policy none --seed-base {seed} --base-port 7600 --timeout 900")
            r = sh(cmd, timeout=1200)
            p = sh(f"docker exec {CONTAINER} sh -lc 'ls {RUNDIR}/{tag}/0/*.sav.zst 2>/dev/null | head -1'")
            sp = p.stdout.strip()
            if not sp:
                print(f"раунд {rnd}: нет сейва, пропуск", flush=True)
                continue
            sh(f"docker cp {CONTAINER}:{sp} {save_host}.zst")
            z = sh(f"zstd -dc {save_host}.zst > {save_host}")
            if z.returncode != 0 or os.path.getsize(save_host) == 0:
                print(f"раунд {rnd}: не распаковался", flush=True)
                continue
        P = parse_save(save_host)
        J = sh(f"docker exec {CONTAINER} sh -lc 'cat {RUNDIR}/{tag}/0/stdout.txt'").stdout
        by_name = {v["name"]: k for k, v in P.items()}
        for d in dead:
            name = d["name"]
            pid = by_name.get(name)
            founded = [(c["name"], P[o]["name"], int(o)) for o, v in P.items()
                       for c in v["cities"] if str(c["original"]) == str(pid)]
            owners = {}
            for cname, oname, _ in founded:
                owners[oname] = owners.get(oname, 0) + 1
            declares, attacks, last_turn = analyse_journal(J, name)
            attackers = {}
            for a in attacks:
                attackers[a["owner"]] = attackers.get(a["owner"], 0) + 1
            result.append({
                "round": rnd, "seed": seed, "seat": name, "nation": d["nation"],
                "player_id": pid, "turns_seen": last_turn,
                "founded_cities_total": len(founded),
                "cities_now": dict(owners),
                "captured_cities": [{"city": c, "owner": o} for c, o, _ in founded],
                "declares": declares,
                "attacks_by": attackers,
                "attacks_total": len(attacks),
                "units_lost": d.get("units_lost"), "units_killed": d.get("units_killed"),
                "techs": d.get("techs"),
                "verified_same_game": (sec["units_killed"] == json.load(
                    open(os.path.join(EXP, "rounds", f"round_{rnd:04d}.json"),
                         encoding="utf-8"))["sections"]["nodof"]["units_killed"]),
            })
            print(f"раунд {rnd} {name}: городов основано {len(founded)} "
                  f"({owners or 'все разрушены'}), атак на него {len(attacks)} "
                  f"от {attackers or '-'}, объявлений {len(declares)}", flush=True)
    with open(os.path.join(EXP, "deaths.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("записано:", len(result))


if __name__ == "__main__":
    main()
