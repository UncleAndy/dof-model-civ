#!/usr/bin/env python3
"""Раунды A/B/C: одна карта (один сид), три партии — без DOF, с DOF у всех, 50/50.

Раунд = три партии с одинаковым gameseed/mapseed. Партии идут параллельно на
разных портах, каждая в своём каталоге контейнера и со своим jsonl, затем
переносятся в один json раунда разделами (`nodof`, `dof`, `half`); исходные
файлы удаляются — перемешать нельзя.

  ab_rounds.py --count 10 --start 0 --turns 3000
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "deploy", "freeciv-dof", "logs", "series")
RUN = os.path.join(ROOT, "deploy", "freeciv-dof", "run_series.py")
PY = os.path.join(ROOT, ".venv", "bin", "python")
CONTAINER = "freeciv-web"
RUNDIR = "/home/docker/dofrun/series"
BIN = "/home/docker/freeciv/bin/freeciv-web"
# Ручки раунда: без DOF, DOF у всех мест, DOF через одно место (50/50).
# Политика "even" включает DOF для чётных мест — это и есть половина состава.
ARMS = (("nodof", "none", 7600), ("dof", "all", 7700), ("half", "even", 7800))
SAVE_SUFFIX = {"nodof": "no_dof", "dof": "dof", "half": "half"}


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg, out):
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with open(os.path.join(out, "driver.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def sh(cmd, timeout=300):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def engine_md5():
    r = sh(f"docker exec {CONTAINER} md5sum {BIN}")
    return r.stdout.split()[0] if r.stdout else "?"


def stand_ready(timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        r = sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7002/", timeout=10)
        if r.stdout.strip() == "200":
            return True
        time.sleep(3)
    return False


def restart_stand(out):
    log("перезапуск стенда", out)
    sh(f"docker restart {CONTAINER}", timeout=180)
    ok = stand_ready()
    log(f"стенд {'готов' if ok else 'НЕ ответил'} после перезапуска", out)
    return ok


def clear_stale(port, out):
    """Убить зависший движок на порту, если он остался от прошлой попытки."""
    # Скобка в последней цифре, чтобы шаблон не совпал с собственной командой pgrep.
    sport = str(port)
    pat = f"freeciv-web.*--port {sport[:-1]}[{sport[-1]}] "
    r = sh(f"docker exec {CONTAINER} sh -lc 'pgrep -f \"{pat}\" || true'")
    pids = r.stdout.split()
    if pids:
        log(f"снимаю зависшие движки на {port}: {pids}", out)
        sh(f"docker exec {CONTAINER} sh -lc 'kill {' '.join(pids)} 2>/dev/null || true'")
        time.sleep(2)


def mapgen_failed(rnd):
    """Признак отказа генерации карты: движок не смог расставить стартовые позиции."""
    for name, _, _ in ARMS:
        d = f"{RUNDIR}/ab{rnd:04d}{name}"
        r = sh(f"docker exec {CONTAINER} sh -lc 'grep -qa \"allocate starting positions\" "
               f"{d}/stdout.txt 2>/dev/null && echo yes'")
        if r.stdout.strip() == "yes":
            return True
    return False


def last_row(tag):
    path = os.path.join(LOGS, f"{tag}.jsonl")
    if not os.path.exists(path):
        return None
    row = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
    return row


def parse_journal(stdout_text):
    """Краткая выжимка журнала DOF: счётчики и образцы событий."""
    out = {"policy": None, "roster_dof": None, "declares": [], "attacks": [],
           "blocked": 0, "suppressed": 0, "cease_expiry": 0, "unit_source": 0,
           "on_source": 0}
    for line in stdout_text.splitlines():
        if "[DOF] policy=" in line:
            m = re.search(r"policy=(\w+)", line)
            if m:
                out["policy"] = m.group(1)
        elif "[DOF] roster" in line:
            out["roster_dof"] = line.split("ai_seats=", 1)[-1][:400]
        elif "[DOF] declare" in line and len(out["declares"]) < 40:
            out["declares"].append(line[:220])
        elif "[DOF] attack" in line and len(out["attacks"]) < 40:
            out["attacks"].append(line[:220])
        elif "[DOF] blocked" in line:
            out["blocked"] += 1
        elif "[DOF] suppressed" in line:
            out["suppressed"] += 1
        elif "[DOF] cease_expiry" in line:
            out["cease_expiry"] += 1
        elif "[DOF] unit_source_on_source" in line:
            # M7: нападение на уже объявленный источник — не коллапс.
            out["on_source"] += 1
        elif "[DOF] unit_source" in line:
            out["unit_source"] += 1
    return out


def save_facts(path):
    """Разбор финального сейва: ход, год, состояние корабля у каждого места.

    Космические достижения в обычной игре завершают партию, поэтому пишем их
    отдельно: state 0 — не строился, 1 — строится, 2 — запущен, 3 — долетел.
    """
    r = subprocess.run(["zstd", "-dc", path], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return {"turn": None, "year": None, "players": {}}
    turn = year = None
    players, cur = {}, None
    for line in r.stdout.splitlines():
        if cur is None:
            if turn is None and line.startswith("turn="):
                turn = int(line.split("=", 1)[1] or 0)
            elif year is None and line.startswith("year="):
                year = int(line.split("=", 1)[1] or 0)
        m = re.match(r"^\[player(\d+)\]$", line)
        if m:
            cur = {"id": int(m.group(1))}
            players[cur["id"]] = cur
            continue
        if line.startswith("["):
            cur = None
            continue
        if cur is None or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k in ("name", "nation", "is_alive"):
            cur[k] = v.strip().strip('"')
        elif k.startswith("spaceship."):
            kk = k.split(".", 1)[1]
            try:
                cur["sship_" + kk] = int(v)
            except ValueError:
                pass
    return {"turn": turn, "year": year, "players": players}


def play(arm, policy, port, tag, seed, args, out, rnd):
    """Одна партия. Возвращает раздел раунда; бросает исключение при сбое."""
    jsonl = os.path.join(LOGS, f"{tag}.jsonl")
    if os.path.exists(jsonl):
        os.remove(jsonl)
    # Пустой каталог до старта: иначе движок подхватит чужой/старый сейв
    # и раунд получит данные от другой партии.
    sh(f"docker exec {CONTAINER} sh -lc 'rm -rf {RUNDIR}/{tag}'")
    clear_stale(port, out)
    cmd = [PY, RUN, "--tag", tag, "--games", "1", "--turns", str(args.turns),
           "--aifill", str(args.aifill), "--size", str(args.size), "--par", "1",
           "--policy", policy, "--seed-base", str(seed), "--base-port", str(port),
           "--timeout", str(args.timeout)]
    for extra in (getattr(args, "set", None) or []):
        cmd += ["--set", extra]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout + 300)
    secs = round(time.time() - t0, 1)
    row = last_row(tag)
    if not row:
        r = sh(f"docker exec {CONTAINER} sh -lc 'grep -qa \"allocate starting positions\" "
               f"{RUNDIR}/{tag}/0/stdout.txt 2>/dev/null && echo yes'")
        if r.stdout.strip() == "yes":
            raise RuntimeError(f"MAPGEN {tag}: карта под этот сид не генерируется")
        raise RuntimeError(f"{tag}: нет строки результата (rc={proc.returncode}) "
                           f"{proc.stderr[-300:]}")
    if row.get("failed"):
        r = sh(f"docker exec {CONTAINER} sh -lc 'grep -qa \"allocate starting positions\" "
               f"{RUNDIR}/{tag}/0/stdout.txt 2>/dev/null && echo yes'")
        if r.stdout.strip() == "yes":
            raise RuntimeError(f"MAPGEN {tag}: карта под этот сид не генерируется")
        raise RuntimeError(f"{tag}: {row['failed']}")

    d = f"{RUNDIR}/{tag}/0"
    r = sh(f"docker exec {CONTAINER} sh -lc 'cd {d} && ls -1 *.sav.zst 2>/dev/null | head -1'")
    save = r.stdout.strip()
    if not save:
        raise RuntimeError(f"{tag}: в каталоге нет финального сейва")
    r = sh(f"docker exec {CONTAINER} sh -lc 'cd {d} && sha256sum {save} && stat -c %s {save} "
           f"&& grep -hE \"^set (game|map)seed\" s.serv 2>/dev/null'")
    lines = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    sha = lines[0].split()[0] if lines else "?"
    size = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else 0
    seeds_in = sorted({x.split()[-1] for x in lines[2:]})
    if seeds_in and seeds_in != [str(seed)]:
        raise RuntimeError(f"{tag}: в s.serv сид {seeds_in}, ожидался {seed}")
    # Какие настройки завершения игры реально попали в s.serv: по ним видно,
    # отключены ли победы (disabled) или действуют по умолчанию.
    r = sh(f"docker exec {CONTAINER} sh -lc 'cat {d}/s.serv'")
    victory_settings = {}
    for ln in r.stdout.splitlines():
        parts = ln.strip().split(None, 2)
        if (len(parts) == 3 and parts[0] == "set"
                and parts[1] in ("victories", "endspaceship", "endvictory")):
            victory_settings[parts[1]] = parts[2].strip()
    r = sh(f"docker exec {CONTAINER} sh -lc 'cd {d} && wc -c < stdout.txt'")
    stdout_bytes = int(r.stdout.strip() or 0)
    r = sh(f"docker exec {CONTAINER} sh -lc 'cd {d} && cat stdout.txt'", timeout=120)
    journal = parse_journal(r.stdout)

    section = {
        "tag": tag, "policy": policy, "seed": seed, "port": port, "secs": secs,
        "save": {"file": save, "sha256": sha, "bytes": size},
        "stdout_bytes": stdout_bytes,
        "turns": row["turns"], "aifill": row["aifill"], "size": row["size"],
        "players": row["players"], "alive": row["alive"],
        "eliminated": row["eliminated"],
        "units_killed": row["units_killed"], "units_lost": row["units_lost"],
        "barb_units_lost": row.get("barb_units_lost", 0),
        "barb_units_killed": row.get("barb_units_killed", 0),
        "barb_players": row.get("barb_players", 0),
        "dof_declares": row["dof_declares"],
        "dof_declares_dof_seats": row.get("dof_declares_dof_seats", 0),
        "dof_news": row.get("dof_news", 0),
        "dof_blocked": row["dof_blocked"], "dof_suppressed": row["dof_suppressed"],
        "dof_roster": row.get("dof_roster"),
        "journal": journal,
        "nations": row["nations"],
    }
    # Финальный сейв кладём рядом с результатами, с человекочитаемым именем.
    save_dir = os.path.join(out, "rounds", "saves")
    os.makedirs(save_dir, exist_ok=True)
    host_save = os.path.join(save_dir, f"save_round_{rnd}_{SAVE_SUFFIX[arm]}.sav.zst")
    sh(f"docker cp {CONTAINER}:{d}/{save} {host_save}")
    facts = save_facts(host_save)

    # Достижения, которые в обычной игре завершают партию: состояние корабля
    # по местам (2 — запущен, 3 — долетел) и культура.
    sship = {p.get("name"): p for p in facts["players"].values()}
    for n in row["nations"]:
        p = sship.get(n.get("name")) or {}
        n["spaceship_state"] = p.get("sship_state", 0)
        for kk in ("structurals", "components", "modules", "fuel", "propulsion",
                   "habitation", "life_support", "solar_panels"):
            if "sship_" + kk in p:
                n["sship_" + kk] = p["sship_" + kk]
    launched = sorted(n["name"] for n in row["nations"]
                      if (n.get("spaceship_state") or 0) >= 2)
    arrived = sorted(n["name"] for n in row["nations"]
                     if (n.get("spaceship_state") or 0) >= 3)
    culture = sorted(((n.get("culture") or 0, n.get("name")) for n in row["nations"]
                      if not n.get("is_barbarian")), reverse=True)
    section["final_turn"] = facts["turn"]
    section["final_year"] = facts["year"]
    section["victory_settings"] = victory_settings
    section["spaceship_launched"] = launched
    section["spaceship_arrived"] = arrived
    section["culture_top"] = ({"name": culture[0][1], "value": culture[0][0]}
                              if culture else None)
    section["culture_second"] = ({"name": culture[1][1], "value": culture[1][0]}
                                 if len(culture) > 1 else None)
    section["conquest_would_be"] = (row["alive"] == 1 and row["players"] > 1)
    sh(f"docker exec {CONTAINER} sh -lc 'rm -rf {RUNDIR}/{tag}'")
    if os.path.exists(jsonl):
        os.remove(jsonl)
    return section


def totals(section):
    nat = [n for n in section["nations"] if not n.get("is_barbarian")]
    def s(k):
        return sum(n.get(k) or 0 for n in nat)
    def m(k):
        v = [n.get(k) for n in nat if n.get(k) is not None]
        return round(sum(v) / len(v), 2) if v else 0
    return {"nations": len(nat), "score_sum": s("score"), "score_mean": m("score"),
            "cities_sum": s("ncities"), "population_sum": s("population_real"),
            "techs_mean": m("techs"), "bulbs_mean": m("bulbs_last_turn"),
            "science_rate_mean": m("science_rate"),
            "units_killed": section["units_killed"], "units_lost": section["units_lost"],
            "alive": section["alive"], "players": section["players"],
            "declares": section["dof_declares"], "attacks": section["dof_news"]}


def _one_arm(rnd, seed, args, out, arm):
    """Одна партия раунда: обёртка для запуска в отдельном потоке."""
    name, policy, port = arm
    tag = f"ab{rnd:04d}{name}"
    sec = play(name, policy, port, tag, seed, args, out, rnd)
    sec["totals"] = totals(sec)
    return name, sec


def cmp_sections(base, sec):
    """Разница метрик одной руки относительно базовой."""
    def d(k):
        return round(sec["totals"].get(k, 0) - base["totals"].get(k, 0), 2)
    ft, bt = sec.get("final_turn"), base.get("final_turn")
    return {"alive_diff": sec["alive"] - base["alive"],
            "kills_diff": sec["units_killed"] - base["units_killed"],
            "declares_diff": sec["dof_declares"] - base["dof_declares"],
            "score_mean_diff": d("score_mean"),
            "bulbs_mean_diff": d("bulbs_mean"),
            "techs_mean_diff": d("techs_mean"),
            "final_turn_diff": (None if ft is None or bt is None else ft - bt)}


def play_round(rnd, seed, args, out):
    data = {"round": rnd, "seed": seed, "started_utc": now(),
            "params": {"turns": args.turns, "aifill": args.aifill, "size": args.size,
                       "engine_md5": engine_md5(), "parallel": True},
            "sections": {}}
    # Все три партии раунда идут одновременно: у каждой свой порт, свой каталог
    # в контейнере и свой jsonl, поэтому данные не перемешиваются.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ARMS)) as ex:
        futs = [(arm[0], ex.submit(_one_arm, rnd, seed, args, out, arm)) for arm in ARMS]
        errors = []
        for _, fut in futs:
            try:
                nm, sec = fut.result()
                data["sections"][nm] = sec
                log(f"раунд {rnd}: {nm} готов ({sec['secs']} c, ход {sec['final_turn']}, "
                    f"живых {sec['alive']}/{sec['players']}, убито {sec['units_killed']}, "
                    f"объявлений {sec['dof_declares']}, "
                    f"кораблей запущено {len(sec['spaceship_launched'])})", out)
            except Exception as e:
                errors.append(e)
    if errors:
        raise errors[0]
    a = data["sections"]["nodof"]
    b = data["sections"]["dof"]
    c = data["sections"]["half"]
    data["comparison"] = {"dof_vs_nodof": cmp_sections(a, b),
                          "half_vs_nodof": cmp_sections(a, c),
                          "half_vs_dof": cmp_sections(b, c)}
    data["finished_utc"] = now()
    return data


def write_round(data, out):
    path = os.path.join(out, "rounds", f"round_{data['round']:04d}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(os.path.join(out, "rounds.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"round": data["round"], "seed": data["seed"],
                            "comparison": data["comparison"],
                            "finished_utc": data["finished_utc"]}, ensure_ascii=False) + "\n")
        f.flush()


def load_done(out):
    done = set()
    d = os.path.join(out, "rounds")
    if not os.path.isdir(d):
        return done
    for name in os.listdir(d):
        m = re.match(r"round_(\d+)\.json$", name)
        if not m:
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                data = json.load(f)
            if {"nodof", "dof", "half"} <= set(data.get("sections", {})):
                done.add(int(m.group(1)))
        except Exception:
            continue
    return done


def summarise(out):
    d = os.path.join(out, "rounds")
    rows = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if {"nodof", "dof", "half"} <= set(data.get("sections", {})):
            rows.append(data)
    if not rows:
        return
    ARMS_NAMES = [a[0] for a in ARMS]

    def agg(arm):
        ts = [r["sections"][arm]["totals"] for r in rows]
        keys = ["score_mean", "score_sum", "cities_sum", "population_sum", "techs_mean",
                "bulbs_mean", "science_rate_mean", "units_killed", "units_lost",
                "alive", "players", "declares", "attacks"]
        o = {"rounds": len(ts)}
        for k in keys:
            o[k] = round(sum(t.get(k, 0) for t in ts) / len(ts), 2)
        # Достижения, которые в обычной игре завершают партию.
        o["spaceship_launched_rounds"] = sum(
            1 for r in rows if r["sections"][arm].get("spaceship_launched"))
        o["spaceship_arrived_rounds"] = sum(
            1 for r in rows if r["sections"][arm].get("spaceship_arrived"))
        o["spaceship_launched_max"] = max(
            (len(r["sections"][arm].get("spaceship_launched") or []) for r in rows),
            default=0)
        o["conquest_rounds"] = sum(
            1 for r in rows if r["sections"][arm].get("conquest_would_be"))
        o["final_turn_mean"] = round(sum(
            (r["sections"][arm].get("final_turn") or 0) for r in rows) / len(rows), 1)
        return o

    summary = {"generated_utc": now(), "rounds_done": len(rows),
               "seed_range": [min(r["seed"] for r in rows), max(r["seed"] for r in rows)],
               "params": rows[0]["params"]}
    for a in ARMS_NAMES:
        summary[a] = agg(a)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("# A/B/C: без DOF, DOF у всех, DOF 50/50\n\n")
        f.write(f"раундов: {len(rows)}, сиды {min(r['seed'] for r in rows)}–"
                f"{max(r['seed'] for r in rows)}, {rows[0]['params']['turns']} ходов, "
                f"aifill {rows[0]['params']['aifill']}, size {rows[0]['params']['size']}, "
                f"движок `{rows[0]['params']['engine_md5']}`, партии раунда параллельно\n\n")
        f.write("| метрика (среднее на раунд) | без DOF | DOF у всех | 50/50 |\n|---|---|---|---|\n")
        names = {"score_mean": "score на место", "cities_sum": "городов всего",
                 "population_sum": "население всего", "techs_mean": "технологий на место",
                 "bulbs_mean": "наука, bulbs/ход", "units_killed": "убито юнитов",
                 "units_lost": "потеряно юнитов", "alive": "живых мест",
                 "players": "мест в партии", "declares": "объявлений войны",
                 "final_turn_mean": "средний финальный ход",
                 "spaceship_launched_rounds": "раундов с запуском корабля",
                 "spaceship_arrived_rounds": "раундов с прибытием корабля",
                 "conquest_rounds": "раундов с завоеванием"}
        for k, label in names.items():
            f.write(f"| {label} | {summary['nodof'].get(k)} | {summary['dof'].get(k)} | "
                    f"{summary['half'].get(k)} |\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--seed-base", type=int, default=40000)
    ap.add_argument("--turns", type=int, default=200)
    ap.add_argument("--aifill", type=int, default=10)
    ap.add_argument("--size", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--set", action="append", default=None, metavar="CMD",
                    help="дополнительная серверная команда, например 'set endspaceship 0'")
    ap.add_argument("--out", default=os.path.join(ROOT, "experiments", "dof-ab-26102026"))
    ap.add_argument("--summary-every", type=int, default=10)
    args = ap.parse_args()

    out = args.out
    os.makedirs(os.path.join(out, "rounds"), exist_ok=True)
    log(f"старт: раунды {args.start}..{args.start + args.count - 1}, "
        f"сид {args.seed_base}+17*r, движок {engine_md5()}", out)
    done = load_done(out)
    log(f"уже готово раундов: {len(done)}", out)
    for rnd in range(args.start, args.start + args.count):
        if rnd in done:
            continue
        seed = args.seed_base + rnd * 17
        alt = 0            # подмена сида, если карта под этот сид не генерируется
        attempt = 0
        while True:
            attempt += 1
            seed_try = seed + alt
            try:
                data = play_round(rnd, seed_try, args, out)
                if alt:
                    data["seed_fallback"] = {"requested": seed, "used": seed_try,
                                             "why": "map generation failed for requested seed"}
                write_round(data, out)
                log(f"раунд {rnd} записан (попытка {attempt}, сид {seed_try})", out)
                break
            except Exception as e:
                log(f"раунд {rnd} попытка {attempt} (сид {seed_try}) провалилась: {e}", out)
                for name, _, port in ARMS:
                    sh(f"docker exec {CONTAINER} sh -lc 'rm -rf {RUNDIR}/ab{rnd:04d}{name}'")
                    for f in (f"{LOGS}/ab{rnd:04d}{name}.jsonl",):
                        if os.path.exists(f):
                            os.remove(f)
                # Отказ генерации карты — не сбой стенда: лечится другим сидом.
                if "MAPGEN" in str(e) and alt < 4:
                    alt += 1
                    log(f"раунд {rnd}: карта под сид {seed_try} не генерируется, "
                        f"пробую {seed + alt}", out)
                    continue
                if attempt >= args.retries:
                    log(f"раунд {rnd}: исчерпаны попытки, раунд пропущен", out)
                    with open(os.path.join(out, "failed_rounds.log"), "a") as f:
                        f.write(f"{rnd}\t{seed}\t{e}\n")
                    break
                restart_stand(out)
        if (rnd - args.start + 1) % args.summary_every == 0:
            summarise(out)
    summarise(out)
    log("ВСЕ ЗАПЛАНИРОВАННЫЕ РАУНДЫ ОБРАБОТАНЫ", out)


if __name__ == "__main__":
    main()
