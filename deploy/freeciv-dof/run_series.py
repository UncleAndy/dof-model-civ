#!/usr/bin/env python3
"""Серии партий встроенного ИИ freeciv: одна рука на серию.

Каждая партия — безлюдный прогон движка в контейнере freeciv-web (`--type autogame`).
По окончании движок пишет финальный сейв (`set autosaves GAMEOVER`), из которого
берётся отчёт по каждой нации: общий score, города, население, юниты, наука.
Из журнала `[DOF]` берётся состав мест (кто вёл себя по DOF) и счётчики событий.

  run_series.py --tag classic --policy none --games 6 --turns 200
  run_series.py --tag dof     --policy all  --games 6 --turns 200
  run_series.py --tag mixed   --policy even --games 6 --turns 200

Результат: logs/series/<tag>.jsonl — одна строка на партию, докатка по готовым строкам.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(ROOT, "logs", "series")
CONTAINER = "freeciv-web"
RUNDIR = "/home/docker/dofrun/series"
BIN = "/home/docker/freeciv/bin/freeciv-web"

# Набор ключей сейва. Значения читаются построчно: векторы (c={...}, u={...})
# пропускаются, потому что их строки не начинаются с нужных ключей.
PLAYER_KEYS = {
    "name": r'^name="(.*)"$',
    "nation": r'^nation="(.*)"$',
    "ai_type": r'^ai_type="(.*)"$',
    "is_alive": r"^is_alive=(\w+)$",
    "gov": r'^government_name="(.*)"$',
    "gold": r"^gold=(-?\d+)$",
    "science_rate": r"^rates\.science=(\d+)$",
    "bulbs_last_turn": r"^research\.bulbs_last_turn=(-?\d+)$",
    "turns_alive": r"^turns_alive=(\d+)$",
    "ncities": r"^ncities=(\d+)$",
    "nunits": r"^nunits=(\d+)$",
}
SCORE_KEYS = {
    "score": r"^total=(-?\d+)$",
    "population": r"^population=(-?\d+)$",
    "cities": r"^cities=(\d+)$",
    "units": r"^units=(\d+)$",
    "techs": r"^techs=(\d+)$",
    "techout": r"^techout=(-?\d+)$",
    "units_built": r"^units_built=(\d+)$",
    "units_killed": r"^units_killed=(\d+)$",
    "units_lost": r"^units_lost=(\d+)$",
    "landarea": r"^landarea=(\d+)$",
    "literacy": r"^literacy=(\d+)$",
    "bnp": r"^bnp=(\d+)$",
    "mfg": r"^mfg=(\d+)$",
    "culture": r"^culture=(-?\d+)$",
    "wonders": r"^wonders=(\d+)$",
}

RX = {
    "policy": re.compile(r"\[DOF\] policy=(\S+) turn=(\d+)"),
    # Строка состава может быть обрезана буфером лога при >12 местах, поэтому
    # закрывающую скобку не требуем.
    "roster": re.compile(r"\[DOF\] roster ai_seats=\[(.*)"),
    "declare": re.compile(r"\[DOF\] declare turn=(\d+) declarer=(.+?) target=(.+?) "
                          r"declarer_dof=(\d) reason=(\d)"),
    "news": re.compile(r"\[DOF\] news turn=(\d+) violator=(.+?) victim=(.+?) "
                       r"violator_dof=(\d) victim_dof=(\d)"),
    "blocked": re.compile(r"\[DOF\] blocked turn=(\d+)"),
    "suppressed": re.compile(r"\[DOF\] desire_suppressed"),
}


def sh(cmd, check=False):
    """docker exec без shell на стороне хоста: аргументы уходят списком."""
    r = subprocess.run(["docker", "exec", CONTAINER, "sh", "-lc", cmd],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker exec failed: {cmd}\n{r.stderr[:400]}")
    return r


def q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def setup_game(tag, idx, args):
    d = f"{RUNDIR}/{tag}/{idx}"
    # Один и тот же сид у всех рук: руки сравниваются на одинаковых картах.
    seed = 1000 + idx * 17
    serv = "\n".join([
        f"set aifill {args.aifill}",
        "set minp 0",
        f"set endt {args.turns}",
        f"set size {args.size}",
        "set autosaves GAMEOVER",
        f"set savename dof-{tag}-{idx}",
        f"set gameseed {seed}",
        f"set mapseed {seed}",
        "start",
        "",
    ])
    sh(
        f"mkdir -p {d} && chmod 777 {d} && "
        f"printf '%s\\n' {q(args.policy)} > {d}/policy.conf && chmod 666 {d}/policy.conf && "
        f"printf '%s' {q(serv)} > {d}/s.serv && chmod 666 {d}/s.serv",
        check=True,
    )
    return d


def launch(d, port, args):
    inner = (
        f"cd /docker/publite2 && env DOF_POLICY_FILE={d}/policy.conf sh -c "
        # --debug 1: на уровне 2 движок пишет сотни мегабайт лога за десяток ходов,
        # а журнал DOF всё равно дублируется в stderr (stdout.txt).
        f"{q(f'printf \"start\\n\" | timeout {args.timeout} {BIN} --debug 1 --type autogame '
            f'--read pubscript_autogame.serv --read {d}/s.serv --port {port} '
            f'--exit-on-end --saves {d} --scenarios {d} '
            f'--log {d}/game.log > {d}/stdout.txt 2>&1')}"
    )
    sh(f"nohup sh -c {q(inner)} > /dev/null 2>&1 & disown; true")


def final_save(d):
    """Движок этой сборки жмёт сейвы через zstd (.sav.zst), старые — .sav.xz."""
    r = sh(f"ls -t {d}/*.sav.zst {d}/*.sav.xz {d}/*.sav.gz 2>/dev/null | head -1")
    return r.stdout.strip() or None


def read_save(path):
    """Сейв забираем в контейнера и распаковываем на хосте: в образе нет zstd-cli,
    а движок жмёт именно zstd."""
    ext = path.rsplit(".", 1)[-1]
    tmp = tempfile.mkdtemp(prefix="dofsave-")
    local = os.path.join(tmp, os.path.basename(path))
    r = subprocess.run(["docker", "cp", f"{CONTAINER}:{path}", local],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"docker cp failed for {path}: {r.stderr[:300]}")
    cmd = {"zst": ["zstd", "-dc", local],
           "xz": ["xz", "-dc", local],
           "gz": ["zcat", local]}[ext]
    r = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        raise RuntimeError(f"cannot decompress {path}: {r.stderr[:300]}")
    return r.stdout


def engine_alive(d):
    # Путь партии в шаблоне обязателен: иначе pgrep ловит чужие движки серии.
    # [s] — чтобы pgrep не нашёл сам себя: своя командная строка содержит
    # «[s].serv» буквально, а у движка в аргументах стоит «s.serv».
    r = sh(f"pgrep -f {q(d + '/[s].serv')} > /dev/null && echo yes")
    return r.stdout.strip() == "yes"


def parse_save(text):
    players, scores, cur = {}, {}, None
    city_sizes = {}
    in_city = False
    for line in text.splitlines():
        if line.startswith("c={"):
            in_city, guard = True, 0
            continue
        if in_city:
            if line == "}":
                in_city = False
                continue
            parts = line.split(",")
            if len(parts) > 5 and cur and cur[0] == "p":
                try:
                    city_sizes.setdefault(cur[1], []).append(int(parts[4]))
                except ValueError:
                    pass
            continue
        if m := re.match(r"^\[player(\d+)\]$", line):
            cur = ("p", int(m.group(1)))
            players[cur[1]] = {}
            continue
        if m := re.match(r"^\[score(\d+)\]$", line):
            cur = ("s", int(m.group(1)))
            scores[cur[1]] = {}
            continue
        if line.startswith("["):
            cur = None
            continue
        if cur is None:
            continue
        table = PLAYER_KEYS if cur[0] == "p" else SCORE_KEYS
        for key, rx in table.items():
            m = re.match(rx, line)
            if m:
                val = m.group(1)
                if val in ("TRUE", "FALSE"):
                    val = val == "TRUE"
                elif re.fullmatch(r"-?\d+", val):
                    val = int(val)
                (players if cur[0] == "p" else scores)[cur[1]][key] = val
    # Настоящее население — сумма размеров городов: score.population в сейве
    # это очки счёта, а не граждане (проверено: 10 граждан дают 120 очков).
    out = []
    for pid in sorted(players):
        sizes = city_sizes.get(pid, [])
        row = {"id": pid, "city_sizes": sorted(sizes, reverse=True),
               "population_real": sum(sizes)}
        row.update(players[pid])
        row.update(scores.get(pid, {}))
        row["is_barbarian"] = row.get("nation") in ("Barbarian", "Pirate")
        out.append(row)
    return out


def parse_log(path):
    # Лог партии — десятки мегабайт, поэтому грепаем в контейнере, а не тянем целиком.
    d = os.path.dirname(path)
    text = sh(f"grep -a -h -E '\\[DOF\\]|Removing player' "
              f"{d}/stdout.txt {d}/game.log 2>/dev/null").stdout
    info = {"roster": None, "policy": None, "declares": [], "news": [],
            "blocked": 0, "suppressed": 0, "removed": [], "seats": {}}
    for line in text.splitlines():
        if m := re.search(r"Removing player (\S+)\.", line):
            info["removed"].append(m.group(1))
            continue
        if "[DOF]" not in line:
            continue
        if m := RX["policy"].search(line):
            info["policy"] = m.group(1)
        elif m := RX["roster"].search(line):
            info["roster"] = m.group(1)
        elif m := RX["declare"].search(line):
            info["declares"].append([int(m.group(1)), m.group(2), m.group(3),
                                     int(m.group(4)), int(m.group(5))])
        elif m := RX["news"].search(line):
            info["news"].append([int(m.group(1)), m.group(2), m.group(3),
                                 int(m.group(4)), int(m.group(5))])
        elif RX["blocked"].search(line):
            info["blocked"] += 1
        elif RX["suppressed"].search(line):
            info["suppressed"] += 1
    return info


def run_game(tag, idx, args, lock, fh):
    port = args.base_port + idx
    d = setup_game(tag, idx, args)
    t0 = time.time()
    launch(d, port, args)
    save = None
    while time.time() - t0 < args.timeout:
        time.sleep(8)
        alive = engine_alive(d)
        save = final_save(d)
        if save and not alive:
            break
        if not alive and time.time() - t0 > 30:
            break
    secs = int(time.time() - t0)
    if not save:
        row = {"tag": tag, "game": idx, "port": port, "failed": "no final save",
               "secs": secs}
        with lock:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
        return row
    nations = parse_save(read_save(save))
    log = parse_log(f"{d}/game.log")
    # Считаем только ИИ-места из состава партии (журнал roster): варвары, пираты
    # и пустой слот «Unassigned» в состязании не участвуют.
    roster_names = set()
    if log["roster"]:
        for item in log["roster"].split(","):
            roster_names.add(item.split(":")[0].strip())
    # Состав берём из сейва: там перечислены все места партии, и он не
    # обрезается буфером лога при большом числе игроков. Журнальный roster
    # оставляем как есть в поле dof_roster — он может быть усечён.
    free = [n for n in nations
            if not n.get("is_barbarian") and n.get("name") != "Unassigned"]
    # Варвары (пираты и сухопутные варвары) в состязании не участвуют, но их
    # потери — это убитые варварские юниты. Считаем отдельно: без этого
    # «убито/партию» нельзя разделить на варваров и обычные юниты.
    barbs = [n for n in nations if n.get("is_barbarian")]
    alive_free = [n for n in free if n.get("is_alive")]
    row = {
        "tag": tag, "game": idx, "port": port, "secs": secs,
        "turns": args.turns, "aifill": args.aifill, "size": args.size,
        "policy": args.policy, "save": os.path.basename(save),
        "players": len(free),
        "alive": len(alive_free),
        "eliminated": max(0, len(free) - len(alive_free)),
        "units_killed": sum(n.get("units_killed", 0) for n in free),
        "units_lost": sum(n.get("units_lost", 0) for n in free),
        "barb_units_lost": sum(n.get("units_lost", 0) for n in barbs),
        "barb_units_killed": sum(n.get("units_killed", 0) for n in barbs),
        "barb_players": len(barbs),
        "barb_nations": [n.get("nation") for n in barbs],
        "dof_roster": log["roster"],
        "dof_declares": len(log["declares"]),
        "dof_declares_dof_seats": sum(1 for d in log["declares"] if d[3] == 1),
        "dof_news": len(log["news"]),
        "dof_news_dof_violator": sum(1 for d in log["news"] if d[3] == 1),
        "dof_blocked": log["blocked"],
        "dof_suppressed": log["suppressed"],
        "nations": free,
    }
    with lock:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
    print(f"[{tag}] game {idx} готов: {secs} c, живых {row['alive']}/{row['players']}, "
          f"убито юнитов {row['units_killed']}", flush=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--policy", required=True, choices=["none", "all", "even", "odd"])
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--turns", type=int, default=200)
    ap.add_argument("--aifill", type=int, default=8)
    ap.add_argument("--size", type=int, default=3)
    ap.add_argument("--par", type=int, default=3)
    ap.add_argument("--base-port", type=int, default=6200)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    os.makedirs(LOGS, exist_ok=True)
    path = os.path.join(LOGS, f"{args.tag}.jsonl")
    done = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not r.get("failed"):
                    done.add(r["game"])
    todo = [i for i in range(args.games) if i not in done]
    print(f"[{args.tag}] policy={args.policy} turns={args.turns} "
          f"aifill={args.aifill} size={args.size} запускаю {len(todo)} партий "
          f"(par={args.par})", flush=True)

    lock = threading.Lock()
    with open(path, "a", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=args.par) as pool:
        futures = [pool.submit(run_game, args.tag, i, args, lock, fh) for i in todo]
        for fut in futures:
            fut.result()
    print(f"[{args.tag}] готово", flush=True)


if __name__ == "__main__":
    main()
