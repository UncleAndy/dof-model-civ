"""Запись игры агента в видео: штатные кадры CivRealm + сборка ffmpeg.

Как это работает (проверено): CivRealm умеет снимать кадр клиента freeciv-web на каждом шаге
(`debug.take_screenshot`), для чего поднимает headless-браузер и заходит в партию НАБЛЮДАТЕЛЕМ.
Кадры складываются в `civrealm/logs/screenshots/<пользователь>_<порт>_<дата>/turn_NNN_step_NNNN.png`,
а этот скрипт собирает из них mp4.

Запуск:
  V2_SEEDS=9000 V2_TURNS=60 V2_PORT_BASE=6300 \
  python scripts/v2_record.py
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402
from civrealm.freeciv.utils.freeciv_logging import log_dir  # noqa: E402

from baselines import wedges  # noqa: E402
from brain.v2.agent import Agent  # noqa: E402

STORE = os.environ.get("V2_STORE", str(ROOT / "knowledge" / "world.json"))
TRACE = os.environ.get("V2_TRACE", str(ROOT / "knowledge" / "traces_record.jsonl"))
TURNS = int(os.environ.get("V2_TURNS", "60"))
SEEDS = [int(s) for s in os.environ.get("V2_SEEDS", "9000").split(",")]
PORT_BASE = int(os.environ.get("V2_PORT_BASE", "6300"))
FPS = int(os.environ.get("V2_FPS", "6"))
STEP_TIMEOUT = float(os.environ.get("V2_STEP_TIMEOUT", "30"))
MAX_DECISIONS_PER_TURN = 8
SHOTS_ROOT = Path(log_dir) / "screenshots"


class StepTimeout(Exception):
    pass


def _on_alarm(_sig, _frm):
    raise StepTimeout()


signal.signal(signal.SIGALRM, _on_alarm)


def step(env, action):
    signal.setitimer(signal.ITIMER_REAL, STEP_TIMEOUT)
    try:
        return env.step(action)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _frames_since(before: set[Path]) -> list[Path]:
    now = set(SHOTS_ROOT.rglob("*.png")) if SHOTS_ROOT.exists() else set()
    return sorted(now - before)


def _ffmpeg_path() -> Optional[str]:
    """ffmpeg может не попасть в PATH процесса: ищем и по nix-хранилищу."""
    import glob
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    for pat in ("/nix/store/*-ffmpeg-*/bin/ffmpeg", "/nix/store/*-ffmpeg-full-*/bin/ffmpeg"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def _to_video(frames: list[Path], out: Path, fps: int) -> bool:
    if not frames:
        return False
    ff = _ffmpeg_path()
    if ff is None:
        print("  ffmpeg не найден — кадры остались как PNG")
        return False
    # кадры называются turn_NNN_step_NNNN — берём список по порядку имён и подаём ffmpeg списком
    listfile = out.with_suffix(".txt")
    # АБСОЛЮТНЫЕ пути: ffmpeg разрешает относительные пути от каталога списка, а не от cwd
    listfile.write_text("".join(f"file '{f.resolve()}'\nduration {1.0 / fps:.4f}\n"
                               for f in frames))
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
           "-vsync", "vfr", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
           str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        print("  ffmpeg не запустился:", str(exc)[:140])
        return False
    if r.returncode != 0:
        print("  ffmpeg вернул ошибку:", r.stderr.strip().splitlines()[-1][:160])
        return False
    return True


def play(agent: Agent, seed: int, port: int, turns: int) -> dict:
    fc_args["client_port"] = port
    env = gymnasium.make("civrealm/FreecivBase-v0")
    before = set(SHOTS_ROOT.rglob("*.png")) if SHOTS_ROOT.exists() else set()
    obs, info = env.reset(client_port=port, seed=seed)
    try:
        own_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        own_id = 0
    own_id = own_id or 0
    used: set = set()
    played = actions = 0
    terminated = truncated = False
    try:
        for _ in range(turns):
            for _ in range(MAX_DECISIONS_PER_TURN):
                action = agent.decide(obs, info, own_id, used)
                if action is None:
                    break
                actions += 1
                used.add((action[0], action[1]))
                obs, _r, terminated, truncated, info = step(env, action)
                agent.record_outcome(obs, own_id)
                if terminated or truncated:
                    break
            if terminated or truncated:
                break
            obs, _r, terminated, truncated, info = step(env, None)
            agent.record_outcome(obs, own_id)
            used.clear()
            played += 1
            if terminated or truncated:
                break
    except StepTimeout:
        print("  [клин] шаг не вернулся — партия прервана", flush=True)
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass

    frames = _frames_since(before)
    out = ROOT / "knowledge" / f"game_{seed}_port{port}.mp4"
    ok = _to_video(frames, out, FPS)
    print(f"  кадров {len(frames)} → {'видео ' + str(out) if ok else 'PNG в ' + str(SHOTS_ROOT)}",
          flush=True)

    players = (obs or {}).get("player") or {}
    me = players.get(str(own_id)) or players.get(own_id) or {}
    cities = [c for c in ((obs or {}).get("city") or {}).values() if c.get("owner") == own_id]
    units = [u for u in ((obs or {}).get("unit") or {}).values() if u.get("owner") == own_id]
    return {"seed": seed, "port": port, "ходов_сыграно": played, "счёт": me.get("score"),
            "городов": len(cities), "юнитов": len(units), "действий": actions,
            "кадров": len(frames), "видео": str(out) if ok else None}


def main() -> int:
    fc_args["debug.take_screenshot"] = True      # штатные кадры CivRealm
    fc_args["debug.headless"] = True             # браузер без окна
    agent = Agent(STORE, trace_path=TRACE, avoid=wedges.is_wedged)
    print(f"[запись] база: {STORE}; кадры: {SHOTS_ROOT}")
    results = []
    for i, seed in enumerate(SEEDS):
        port = PORT_BASE + i
        print(f"\n===== партия {i + 1}: сид {seed}, порт {port} =====", flush=True)
        r = play(agent, seed, port, TURNS)
        agent.end_game()
        results.append(r)
        print(f"  итог: {json.dumps(r, ensure_ascii=False)}", flush=True)
    print("\n===== записи =====")
    for r in results:
        print(" ", json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())