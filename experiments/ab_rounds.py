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
import queue
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
# Ручки раунда задаются строкой --arms: "имя:политика;имя:политика;...".
# Политика: none | all | even | odd | rotN | список индексов, например "0,3,6".
#
# rotN — N мест по правилу DOF, причём состав мест меняется от раунда к раунду
# (иначе DOF всегда достаётся одним и тем же индексам и результат можно списать
# на стартовую позицию). Индексы берутся с шагом 3 по кругу из 10.
DEFAULT_ARMS = "nodof:none;dof:all;half:even"
ARMS = ()
SAVE_SUFFIX = {}


def _rot_seats(rnd, k, step=7, stride=3):
    """k индексов мест для DOF: сдвиг на раунд + равномерный шаг по кругу."""
    base = (rnd * step) % 10
    return ",".join(str((base + i * stride) % 10) for i in range(k))


def configure_arms(spec):
    """Разобрать --arms и заполнить ARMS/SAVE_SUFFIX."""
    global ARMS, SAVE_SUFFIX
    arms, suffix = [], {}
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, policy = part.partition(":")
        name, policy = name.strip(), policy.strip()
        if not name or not policy:
            raise SystemExit(f"не разобрал руку: {part!r} (нужно имя:политика)")
        if name in suffix:
            raise SystemExit(f"имя руки повторяется: {name}")
        suffix[name] = name
        arms.append({"name": name, "policy": policy})
    if not arms:
        raise SystemExit("пустой список рук")
    ARMS = tuple(arms)
    SAVE_SUFFIX = suffix
    return ARMS


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
    return r.stdout.split()[0] if r.stdout.strip() else "?"


ENGINE_SRC_DIR = "/docker/freeciv/freeciv/ai/default"
ENGINE_SRC = ("dofpolicy.c", "dofpolicy.h")
MARK_BEGIN = "<!-- engine:begin -->"
MARK_END = "<!-- engine:end -->"
_ENGINE_CACHE = None


def _sha256_file(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return "?"


def _md5_file(path):
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except OSError:
        return "?"


def engine_facts(refresh=False):
    """Версия движка: что именно играло.

    Бинарник — то, что запускается; исходники политики — то, что в него собрано
    (в контейнере и в репозитории, чтобы расхождение было видно); образ — тег и
    id, чтобы прогон можно было повторить на том же стенде. Считается один раз
    за процесс: вызов из потока раунда не должен ходить в docker на каждый раздел.
    """
    global _ENGINE_CACHE
    if _ENGINE_CACHE is not None and not refresh:
        return _ENGINE_CACHE
    src_cont, src_local = {}, {}
    for name in ENGINE_SRC:
        r = sh(f"docker exec {CONTAINER} sh -lc 'md5sum {ENGINE_SRC_DIR}/{name}'")
        src_cont[name] = r.stdout.split()[0] if r.stdout.strip() else "?"
        src_local[name] = _md5_file(os.path.join(ROOT, "deploy", "freeciv-dof", "src", name))
    r = sh("docker inspect --format '{{.Config.Image}} {{.Image}}' " + CONTAINER)
    parts = r.stdout.split()
    _ENGINE_CACHE = {
        "binary_md5": engine_md5(),
        "binary_path": BIN,
        "sources_md5": src_cont,
        "sources_local_md5": src_local,
        "sources_match_local": src_cont == src_local,
        "image_tag": parts[0] if parts else "?",
        "image_id": parts[1] if len(parts) > 1 else "?",
    }
    return _ENGINE_CACHE


def _engine_block(facts, extra=None):
    src = ", ".join(f"`{k}` `{v}`" for k, v in sorted(facts["sources_md5"].items()))
    loc = ", ".join(f"`{k}` `{v}`" for k, v in sorted(facts["sources_local_md5"].items()))
    lines = [MARK_BEGIN, "## Версия движка (записано автоматически)", "",
             f"* записано: {facts['recorded_utc']}",
             f"* бинарник `{facts['binary_path']}`: md5 `{facts['binary_md5']}`",
             f"* образ: `{facts['image_tag']}`, id `{facts['image_id']}`",
             f"* исходники политики в контейнере: {src}",
             "* исходники политики в репозитории: " + loc
             + ("" if facts["sources_match_local"]
                else " — **расходятся с контейнером: играл не тот код, что в репозитории**")]
    if extra:
        lines.append("* параметры старта: " + ", ".join(f"{k}={v}" for k, v in extra.items()))
    lines.append(MARK_END)
    return "\n".join(lines)


def record_engine(out, args=None):
    """Записать версию движка на старте серии: ENGINE.json + блок в SERIES.md.

    Блок в SERIES.md идемпотентен (между маркерами), поэтому повторный старт
    обновляет версию, а не копит абзацы; ручной текст файла не трогается.
    """
    facts = engine_facts(refresh=True)
    facts["recorded_utc"] = now()
    if args is not None:
        facts["start"] = {"turns": getattr(args, "turns", None),
                          "aifill": getattr(args, "aifill", None),
                          "size": getattr(args, "size", None),
                          "arms": getattr(args, "arms", None),
                          "ports": getattr(args, "ports", None),
                          "seed_base": getattr(args, "seed_base", None)}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "ENGINE.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    extra = None
    if args is not None:
        extra = {"ходов": getattr(args, "turns", None), "мест": getattr(args, "aifill", None),
                 "карта": getattr(args, "size", None), "руки": getattr(args, "arms", None),
                 "сид": getattr(args, "seed_base", None)}
    block = _engine_block(facts, extra)
    md = os.path.join(out, "SERIES.md")
    text = ""
    if os.path.exists(md):
        with open(md, encoding="utf-8") as f:
            text = f.read()
    if MARK_BEGIN in text and MARK_END in text:
        head, _, rest = text.partition(MARK_BEGIN)
        _, _, tail = rest.partition(MARK_END)
        text = head + block + tail
    else:
        if not text.strip():
            text = "# Серия: " + (args.arms if args else "?") + "\n"
        text = text.rstrip() + "\n\n" + block + "\n"
    tmp = md + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, md)
    return facts


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
    for a in ARMS:
        d = f"{RUNDIR}/ab{rnd:04d}{a['name']}"
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
        "engine_totals": row.get("totals", {}).get("seats") or {},
        "engine_totals_global": row.get("totals", {}).get("global"),
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
    # Конфиги партии — часть постановки. Каталог в контейнере стирается ниже,
    # поэтому s.serv и policy.conf копируются в артефакты раунда вместе с хешами.
    cfg_dir = os.path.join(out, "rounds", "configs", tag)
    os.makedirs(cfg_dir, exist_ok=True)
    for name in ("s.serv", "policy.conf"):
        sh(f"docker cp {CONTAINER}:{d}/{name} {os.path.join(cfg_dir, name)}")
    section["config"] = {
        "dir": os.path.relpath(cfg_dir, out),
        "s_serv_sha256": _sha256_file(os.path.join(cfg_dir, "s.serv")),
        "policy_file_sha256": _sha256_file(os.path.join(cfg_dir, "policy.conf")),
        "policy_text": policy,
    }

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
    """Агрегаты по МЕСТАМ партии, отдельно от отколовшихся.

    Игрок с id >= 10 — новое место из гражданской войны: оно появляется уже
    по ходу партии, его стартовые условия не сравнимы с местом из состава, и
    среднее по всем нациям смешивает две популяции. Поэтому средние считаются
    по местам 0..9, а отколовшиеся идут отдельными счётчиками.
    """
    nat = [n for n in section["nations"] if not n.get("is_barbarian")]
    seats = [n for n in nat if (n.get("id") or 0) < 10]
    split = [n for n in nat if (n.get("id") or 0) >= 10]
    def s(k, src=None):
        return sum(n.get(k) or 0 for n in (seats if src is None else src))
    def m(k):
        v = [n.get(k) for n in seats if n.get(k) is not None]
        return round(sum(v) / len(v), 2) if v else 0
    return {"totals_schema": 2, "nations": len(nat), "seats": len(seats),
            "splinters": len(split), "splinters_score_sum": s("score", split),
            "splinters_cities_sum": s("ncities", split),
            "score_sum": s("score"), "score_mean": m("score"),
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


def _arm_names():
    return [a["name"] for a in ARMS]


def _policy_of(arm, rnd=0):
    """Политика руки на конкретный раунд: rotN разворачивается в список мест."""
    for a in ARMS:
        if a["name"] == arm:
            pol = a["policy"]
            if pol.startswith("rot"):
                return _rot_seats(rnd, int(pol[3:]))
            return pol
    return "none"


def _round_params(args):
    """Параметры раунда: чем играли (версия движка) и как."""
    facts = engine_facts()
    return {"turns": args.turns, "aifill": args.aifill, "size": args.size,
            "engine_md5": facts["binary_md5"],
            "engine_sources_md5": facts["sources_md5"],
            "engine_image": facts["image_tag"],
            "engine_image_id": facts["image_id"],
            "pool": args.par_games}


def _assemble(rnd, seed, sections, args, alt):
    """Собрать раунд из трёх готовых разделов."""
    data = {"round": rnd, "seed": seed, "started_utc": now(),
            "params": _round_params(args),
            "sections": sections}
    # сравнения — каждая рука с первой (эталон раунда) и все пары между собой
    names = [n for n in _arm_names() if n in sections]
    if names:
        ref = names[0]
        data["comparison"] = {f"{n}_vs_{ref}": cmp_sections(sections[ref], sections[n])
                              for n in names[1:]}
        for i, n1 in enumerate(names):
            for n2 in names[i + 1:]:
                if n1 == ref:
                    continue
                data["comparison"][f"{n2}_vs_{n1}"] = cmp_sections(sections[n1], sections[n2])
    else:
        data["comparison"] = {}
    if alt:
        data["seed_fallback"] = {"requested": args.seed_base + rnd * 17,
                                 "used": seed,
                                 "why": "map generation failed for requested seed"}
    if getattr(args, "seed_override", None):
        data["seed_override"] = {
            "requested": args.seed_base + rnd * 17,
            "used": seed,
            "why": "исходный сид давал игры без финального сейва",
        }
    data["finished_utc"] = now()
    return data


def run_pool(args, out, done):
    """Пул партий: как только одна заканчивается, стартует следующая.

    Одновременно идёт не больше --par-games партий, причём это могут быть
    партии разных раундов. Каждая живёт в своём каталоге контейнера, на своём
    порту и со своим jsonl, поэтому данные не перемешиваются; раунд пишется,
    когда собраны все три его раздела.
    """
    ports = queue.Queue()
    for p in args.ports_list:
        ports.put(p)

    pending, queued = [], set()
    for rnd in range(args.start, args.start + args.count):
        if rnd in done:
            continue
        for a in ARMS:
            pending.append({"rnd": rnd, "arm": a["name"], "alt": 0, "tries": 0})
            queued.add((rnd, a["name"], 0))

    rounds, inflight = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.par_games) as ex:
        while pending or inflight:
            while pending and len(inflight) < args.par_games:
                t = pending.pop(0)
                port = ports.get()
                if getattr(args, "seed_override", None):
                    seed = args.seed_override + t["alt"]
                else:
                    seed = args.seed_base + t["rnd"] * 17 + t["alt"]
                arm = (t["arm"], _policy_of(t["arm"], t["rnd"]), port)
                fut = ex.submit(_one_arm, t["rnd"], seed, args, out, arm)
                inflight[fut] = dict(t, port=port, seed=seed)
            if not inflight:
                break
            finished, _ = concurrent.futures.wait(
                inflight, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in finished:
                info = inflight.pop(fut)
                ports.put(info["port"])
                rnd, arm = info["rnd"], info["arm"]
                state = rounds.setdefault(rnd, {"sections": {}, "alt": 0})
                try:
                    name, sec = fut.result()
                except Exception as e:
                    msg = str(e)
                    if "MAPGEN" in msg:
                        # Карта под этот сид не генерируется: переигрываем весь
                        # раунд на сиде +1, уже собранные разделы отбрасываем.
                        if info["alt"] == state["alt"]:
                            state["alt"] += 1
                            state["sections"].clear()
                            log(f"раунд {rnd}: карта для сида {info['seed']} не генерируется, "
                                f"беру {args.seed_base + rnd * 17 + state['alt']}", out)
                            for a2 in ARMS:
                                key = (rnd, a2["name"], state["alt"])
                                if key not in queued:
                                    queued.add(key)
                                    pending.append({"rnd": rnd, "arm": a2["name"],
                                                    "alt": state["alt"], "tries": 0})
                        continue
                    info["tries"] += 1
                    log(f"раунд {rnd}: {arm} сбой (попытка {info['tries']}): {msg}", out)
                    if info["tries"] < args.retries:
                        pending.insert(0, {"rnd": rnd, "arm": arm,
                                           "alt": info["alt"], "tries": info["tries"]})
                    else:
                        with open(os.path.join(out, "failed_rounds.log"), "a") as f:
                            f.write(f"{rnd}\t{arm}\t{info['seed']}\t{msg}\n")
                    continue
                sec["totals"] = totals(sec)
                state["sections"][name] = sec
                log(f"раунд {rnd}: {name} готов ({sec['secs']} c, ход {sec['final_turn']}, "
                    f"живых {sec['alive']}/{sec['players']}, убито {sec['units_killed']}, "
                    f"объявлений {sec['dof_declares']}, "
                    f"кораблей {len(sec['spaceship_launched'])}, "
                    f"в работе {len(inflight)}/{args.par_games})", out)
                if len(state["sections"]) == len(ARMS) and rnd not in done:
                    data = _assemble(rnd, info["seed"], state["sections"], args, state["alt"])
                    write_round(data, out)
                    done.add(rnd)
                    log(f"раунд {rnd} записан (всего {len(done)} из {args.count})", out)
                    if len(done) % args.summary_every == 0:
                        summarise(out)


def _round_files(d):
    """{номер раунда: имя файла} по каталогу раундов."""
    out = {}
    for name in (os.listdir(d) if os.path.isdir(d) else []):
        m = re.match(r"round_(\d+)\.json$", name)
        if m:
            out[int(m.group(1))] = name
    return out


def _index_row(data, fallback_round=None):
    sections = data.get("sections", {})
    return {"round": data.get("round", fallback_round),
            "seed": data.get("seed"),
            "arms": sorted(sections),
            "games": len(sections),
            "engine_md5": (data.get("params") or {}).get("engine_md5"),
            "finished_utc": data.get("finished_utc")}


def write_index(out, changed=None):
    """Пересобрать rounds.jsonl из rounds/*.json.

    Индекс — производная от файлов раундов, а не второй источник правды:
    строки удалённых/перезаписанных раундов выбрасываются, недостающие
    дочитываются, поэтому обрыв прогона, повтор раунда и правка руками не
    оставляют в индексе дыр и дублей.

    Стоимость: список файлов плюс чтение только тех раундов, которых нет в
    индексе или которые явно изменились (`changed`) — на серии из 1000 раундов
    полная перечитка на каждый раунд была бы квадратичной.
    """
    d = os.path.join(out, "rounds")
    ids = _round_files(d)
    path = os.path.join(out, "rounds.jsonl")
    rows = {}
    if os.path.exists(path) and changed is None:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                n = r.get("round")
                # строка живёт, только если такой раунд есть и в файлах,
                # и строка полная (старый формат индекса не переиспользуем)
                if n in ids and r.get("arms") is not None and r.get("games") is not None:
                    rows[n] = r
    for n, name in sorted(ids.items()):
        if n in rows and n != changed:
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        rows[n] = _index_row(data, n)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for n in sorted(rows):
            f.write(json.dumps(rows[n], ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return len(rows)


def write_round(data, out):
    path = os.path.join(out, "rounds", f"round_{data['round']:04d}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    write_index(out, changed=data["round"])


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
            if set(_arm_names()) <= set(data.get("sections", {})):
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
        if set(_arm_names()) <= set(data.get("sections", {})):
            rows.append(data)
    if not rows:
        return
    ARMS_NAMES = _arm_names()

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
        f.write("# Серия: " + ", ".join(str(a["policy"]) for a in ARMS) + "\n\n")
        f.write(f"раундов: {len(rows)}, сиды {min(r['seed'] for r in rows)}–"
                f"{max(r['seed'] for r in rows)}, {rows[0]['params']['turns']} ходов, "
                f"aifill {rows[0]['params']['aifill']}, size {rows[0]['params']['size']}, "
                f"движок `{rows[0]['params']['engine_md5']}`, партии раунда параллельно\n\n")
        f.write("| метрика (среднее на раунд) | " + " | ".join(ARMS_NAMES) + " |\n")
        f.write("|---" * (len(ARMS_NAMES) + 1) + "|\n")
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
            cells = " | ".join(str(summary[a].get(k)) for a in ARMS_NAMES)
            f.write(f"| {label} | {cells} |\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--seed-base", type=int, default=40000)
    ap.add_argument("--seed-override", type=int, default=None,
                    help="жёсткий сид для всех раундов запуска (вместо seed-base+17*r); "
                         "в файл раунда пишется пометка seed_override")
    ap.add_argument("--turns", type=int, default=200)
    ap.add_argument("--aifill", type=int, default=10)
    ap.add_argument("--size", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--set", action="append", default=None, metavar="CMD",
                    help="дополнительная серверная команда, например 'set endspaceship 0'")
    ap.add_argument("--out", default=os.path.join(ROOT, "experiments", "dof-ab-26102026"))
    ap.add_argument("--summary-every", type=int, default=10)
    ap.add_argument("--par-games", type=int, default=4,
                    help="сколько партий играть одновременно (пул)")
    ap.add_argument("--ports", default="8100,8200,8300,8400",
                    help="порты для пула, через запятую")
    ap.add_argument("--arms", default=DEFAULT_ARMS,
                    help="руки раунда: 'имя:политика;имя:политика'. Политика: "
                         "none|all|even|odd|rotN|список индексов ('0,3,6')")
    args = ap.parse_args()
    configure_arms(args.arms)
    args.ports_list = [int(x) for x in args.ports.split(",") if x.strip()]
    if len(args.ports_list) < args.par_games:
        ap.error("портов меньше, чем партий в пуле")

    out = args.out
    os.makedirs(os.path.join(out, "rounds"), exist_ok=True)
    log(f"старт: раунды {args.start}..{args.start + args.count - 1}, "
        f"сид {args.seed_base}+17*r, движок {engine_md5()}", out)
    done = load_done(out)
    facts = record_engine(out, args)
    log(f"версия движка записана: {facts['binary_md5']} (образ {facts['image_tag']}), "
        f"исходники политики {'совпадают' if facts['sources_match_local'] else 'РАСХОДЯТСЯ'} "
        f"с репозиторием; файлы: ENGINE.json, SERIES.md", out)
    # Длина партии — часть постановки. С включёнными победами партия кончается
    # космосом/завоеванием на любом ходу, и score несравним между руками.
    sets = " ".join(getattr(args, "set", None) or [])
    if "endvictory disabled" not in sets or "endspaceship disabled" not in sets:
        log("ВНИМАНИЕ: победы не отключены — нужны --set 'set endvictory disabled' "
            "и --set 'set endspaceship disabled', иначе партии будут разной длины", out)

    log(f"уже готово раундов: {len(done)}", out)
    run_pool(args, out, done)
    log("ВСЕ ЗАПЛАНИРОВАННЫЕ РАУНДЫ ОБРАБОТАНЫ", out)


if __name__ == "__main__":
    main()
