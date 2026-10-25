#!/usr/bin/env python3
"""Headless A/B series for the DOF policy inside the built-in AI.

Two arms play the SAME scenario (same seeds, same settings):
  control : DOF_POLICY_FILE=none   -> every seat is stock classic AI
  dof     : DOF_POLICY_FILE=<spec> -> seats selected by the spec run DOF

Both arms are single headless servers inside the `freeciv-web` container; the
engine auto-advances turns (server/srv_main.c patch) and writes its own log.
Every run is parsed for the journal lines emitted by ai/default/dofpolicy.c:

  [DOF] roster ...            which seats carry the policy
  [DOF] declare ...           war declaration, with the arm flag of the declarer
  [DOF] attack ...            observed attack incident, both flags
  [DOF] news ...              other diplomatic incidents
  [DOF] blocked ...           a DOF seat was stopped by the policy
  [DOF] contact ...           first contact (DOF seats only)

Usage:
  .venv/bin/python deploy/freeciv-dof/run_ab.py --games 4 --turns 120 \
      --aifill 8 --size 3 --par 4
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

CONTAINER = "freeciv-web"
ENGINE = "/home/docker/freeciv/bin/freeciv-web"
RUN_DIR = "/home/docker/dofrun"
HOST_LOG_DIR = Path(__file__).resolve().parent / "logs" / "ab"

ARM_SPEC = {"control": "none"}


def sh(cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout)


def dexec(script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return sh(f'docker exec -u 0 {CONTAINER} sh -lc {json.dumps(script)}', timeout)


def prepare(game: int, arm: str, spec: str, turns: int, aifill: int,
            size: int, seed: int) -> tuple[str, str]:
    """Write the per-run server script and policy file inside the container."""
    tag = f"{arm}_{game}"
    serv = f"{RUN_DIR}/{tag}.serv"
    pol = f"{RUN_DIR}/pol_{tag}.conf"
    script = (
        f"mkdir -p {RUN_DIR}; "
        f"printf 'set aifill {aifill}\\nset minplayers 0\\nset endturn {turns}\\n"
        f"set size {size}\\nset gameseed {seed}\\nset mapseed {seed}\\nstart\\n' > {serv}; "
        f"printf '{spec}\\n' > {pol}; chmod 666 {serv} {pol}"
    )
    r = dexec(script)
    if r.returncode != 0:
        raise RuntimeError(f"prepare failed: {r.stderr}")
    return serv, pol


def launch(port: int, serv: str, pol: str, tag: str) -> None:
    inner = (f"cd /docker/publite2 && env DOF_POLICY_FILE={pol} sh -c "
             f"'printf \"start\\n\" | timeout 1800 {ENGINE} --type autogame "
             f"--read pubscript_autogame.serv --read {serv} --port {port} "
             f"--exit-on-end --log {RUN_DIR}/{tag}.log > {RUN_DIR}/{tag}.out 2>&1'")
    r = sh(f'docker exec -d {CONTAINER} sh -lc {json.dumps(inner)}')
    if r.returncode != 0:
        raise RuntimeError(f"launch failed on port {port}: {r.stderr}")


def still_running(port: int) -> bool:
    # The engine listens on its own port while the game runs; that is a
    # reliable liveness signal (a `ps | grep <tag>` check matches itself).
    r = dexec(f"ss -ltn 2>/dev/null | grep -q ':{port} ' && echo yes || echo no")
    return r.stdout.strip() == "yes"


def wait_done(ports: dict[str, int], deadline_s: int) -> None:
    start = time.time()
    pending = list(ports)
    while pending and time.time() - start < deadline_s:
        time.sleep(10)
        pending = [t for t in pending if still_running(ports[t])]
    for t in pending:  # reap hung servers so the port is free for the next game
        dexec(f"pkill -f '{t}.serv' || true")


DOF_RE = re.compile(r"\[DOF\] (.+)$", re.M)
DECL_RE = re.compile(r"declare turn=(\d+) declarer=(.+?) target=(.+?) declarer_dof=(\d) reason=(\d+)")
ATK_RE = re.compile(r"attack turn=(\d+) violator=(.+?) victim=(.+?) violator_dof=(\d) victim_dof=(\d)")
NEWS_RE = re.compile(r"news turn=(\d+) violator=(.+?) victim=(.+?) violator_dof=(\d) victim_dof=(\d)")
BLK_RE = re.compile(r"blocked turn=(\d+) me=(.+?) other=(.+?) what=(.+)")
CON_RE = re.compile(r"contact turn=(\d+) me=(.+?) other=(.+?) status=(\w+)")
RULE_RE = re.compile(r"rule turn=(\d+) me=(.+?) other=(.+?) what=(.+)")
SUPP_RE = re.compile(r"desire_suppressed turn=(\d+) me=(.+?) other=(.+?) n=(\d+)")


def parse(log_text: str) -> dict:
    dof = DOF_RE.findall(log_text)
    out = {"dof_lines": len(dof), "declare": [], "attack": [], "news": [],
           "blocked": [], "contact": [], "roster": [], "rule": [],
           "suppressed": []}
    for line in dof:
        m = DECL_RE.match(line)
        if m:
            out["declare"].append({"turn": int(m.group(1)), "declarer": m.group(2),
                                   "target": m.group(3),
                                   "dof": int(m.group(4)), "reason": int(m.group(5))})
            continue
        m = ATK_RE.match(line)
        if m:
            out["attack"].append({"turn": int(m.group(1)), "victim": m.group(3),
                                  "violator": m.group(2),
                                  "violator_dof": int(m.group(4)),
                                  "victim_dof": int(m.group(5))})
            continue
        m = NEWS_RE.match(line)
        if m:
            out["news"].append({"turn": int(m.group(1)), "violator": m.group(2),
                                "victim": m.group(3), "violator_dof": int(m.group(4))})
            continue
        m = BLK_RE.match(line)
        if m:
            out["blocked"].append({"turn": int(m.group(1)), "me": m.group(2),
                                   "other": m.group(3), "what": m.group(4)})
            continue
        m = CON_RE.match(line)
        if m:
            out["contact"].append({"turn": int(m.group(1)), "me": m.group(2),
                                   "other": m.group(3), "status": m.group(4)})
            continue
        m = RULE_RE.match(line)
        if m:
            out["rule"].append({"turn": int(m.group(1)), "me": m.group(2),
                                "other": m.group(3), "what": m.group(4)})
            continue
        m = SUPP_RE.match(line)
        if m:
            out["suppressed"].append({"turn": int(m.group(1)), "me": m.group(2),
                                      "other": m.group(3)})
            continue
        if line.startswith("roster"):
            out["roster"].append(line)
    turns = [int(t) for t in re.findall(r"^3: \[T(\d+)", log_text, re.M)]
    out["max_turn"] = max(turns) if turns else 0
    return out


def collect(tag: str) -> dict:
    HOST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = HOST_LOG_DIR / f"{tag}.log"
    sh(f"docker cp {CONTAINER}:{RUN_DIR}/{tag}.log {log_path}")
    r = dexec(f"tail -c 300 {RUN_DIR}/{tag}.out")
    crashed = "dumped core" in r.stdout or "Segmentation" in r.stdout
    dexec(f"rm -f {RUN_DIR}/{tag}.log {RUN_DIR}/{tag}.out")
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    res = parse(text)
    res.update({"tag": tag, "crashed": crashed, "log_bytes": len(text)})
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--turns", type=int, default=120)
    ap.add_argument("--aifill", type=int, default=8)
    ap.add_argument("--size", type=int, default=3)
    ap.add_argument("--dof-spec", default="even")
    ap.add_argument("--par", type=int, default=4, help="games played in parallel")
    ap.add_argument("--base-port", type=int, default=6100)
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--out", default=str(HOST_LOG_DIR / "series.jsonl"))
    args = ap.parse_args()

    runs = []
    for g in range(args.games):
        seed = args.seed0 + g
        for arm in ("control", "dof"):
            spec = ARM_SPEC[arm] if arm == "control" else args.dof_spec
            runs.append({"game": g, "arm": arm, "spec": spec, "seed": seed})

    results = []
    for start in range(0, len(runs), args.par):
        batch = runs[start:start + args.par]
        ports = {}
        for i, run in enumerate(batch):
            tag = f"{run['arm']}_{run['game']}"
            port = args.base_port + start + i
            serv, pol = prepare(run["game"], run["arm"], run["spec"],
                                args.turns, args.aifill, args.size, run["seed"])
            launch(port, serv, pol, tag)
            ports[tag] = port
            run["tag"] = tag
        wait_done(ports, deadline_s=args.turns * 6 + 300)
        for run in batch:
            res = collect(run["tag"])
            res.update({"arm": run["arm"], "game": run["game"], "seed": run["seed"]})
            results.append(res)
            print(f"{res['tag']:<12} turn={res['max_turn']:<4} "
                  f"decl={len(res['declare'])} atk={len(res['attack'])} "
                  f"rules={len(res['rule'])} "
                  f"blocked={len(res['blocked'])} contacts={len(res['contact'])} "
                  f"crash={res['crashed']}", flush=True)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for res in results:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")

    print("\n--- summary")
    for arm in ("control", "dof"):
        rs = [r for r in results if r["arm"] == arm]
        decl_dof = sum(1 for r in rs for d in r["declare"] if d["dof"] == 1)
        decl_cls = sum(1 for r in rs for d in r["declare"] if d["dof"] == 0)
        atk_dof = sum(1 for r in rs for a in r["attack"] if a["violator_dof"] == 1)
        atk_cls = sum(1 for r in rs for a in r["attack"] if a["violator_dof"] == 0)
        blk = sum(len(r["blocked"]) for r in rs)
        contacts = sum(len(r["contact"]) for r in rs)
        crash = sum(1 for r in rs if r["crashed"])
        rules = sum(len(r["rule"]) for r in rs)
        war_on_source = sum(1 for r in rs for x in r["rule"]
                            if x["what"] == "war_on_source")
        ceasefire = sum(1 for r in rs for x in r["rule"]
                        if x["what"] == "ceasefire_offer")
        coercion = sum(1 for r in rs for x in r["rule"]
                       if x["what"] == "coercion_refused")
        supp = sum(len(r["suppressed"]) for r in rs)
        print(f"{arm:<8} games={len(rs)} rules={rules} "
              f"war_on_source={war_on_source} ceasefire={ceasefire} "
              f"coercion_refused={coercion} desire_suppressed={supp} "
              f"declare[dof]={decl_dof} "
              f"declare[classic]={decl_cls} attacks[dof]={atk_dof} "
              f"attacks[classic]={atk_cls} blocked={blk} contacts={contacts} "
              f"crashes={crash}")
    print(f"\nraw: {args.out}")


if __name__ == "__main__":
    sys.exit(main())
