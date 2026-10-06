"""Запись партии `v0.11` в видео: штатные кадры CivRealm + сборка ffmpeg.

Запуск (порт занимает стенд, поэтому брать свежий и свободный):

    P=$PWD; SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
    PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP" PYTHONWARNINGS=ignore \
    V011_SEEDS=9100 V011_TURNS=60 V011_PORT=6001 DOF_RUN_TAG=rec1 \
    .venv/bin/python scripts/v011_record.py --port 6001

**Что делает этот скрипт, а что мир.** Мир снимает кадры (`debug.take_screenshot`), мы собираем mp4
и наносим текст состояния (`env/video.py` — вся механика, перенесённая из `v2`). Модель сюда не
входит: решение о действии берётся из `decide()`, по умолчанию — **закрытие хода**. Точка проводки
живого агента `v0.11` — ровно эта функция.

**Почему по умолчанию закрытие хода.** Живой цикл решений `v0.11` ещё не портирован (в `scripts/`
ветки — только осмотры и замеры). Записывать «нечего играть» честнее, чем изображать агента: механизм
записи проверяется целиком, а решение подставляется, когда появится.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Callable, Optional

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env import video as V  # noqa: E402


def _args() -> dict[str, Any]:
    import argparse
    ap = argparse.ArgumentParser(description="Запись партии v0.11 в видео")
    ap.add_argument("--port", type=int, default=int(os.environ.get("V011_PORT", "6001")),
                    help="порт стенда (свежий и свободный)")
    ap.add_argument("--seed", type=int, default=int(os.environ.get("V011_SEED", "9100")))
    ap.add_argument("--turns", type=int, default=int(os.environ.get("V011_TURNS", "60")))
    ap.add_argument("--fps", type=int, default=int(os.environ.get("V011_FPS", "6")))
    ap.add_argument("--overview", action="store_true",
                    help="вклеивать обзорную карту (по умолчанию — без оверлея, общим планом)")
    ap.add_argument("--no-fog", action="store_true",
                    help="снимать наблюдателем (вся карта без тумана)")
    return vars(ap.parse_args())


def _obs_state(obs, own_id: int = 0) -> dict[str, Any]:
    """Публикуемое состояние партии — для итоговой строки и различения обрыва от потери всего."""
    obs = obs or {}
    players = obs.get("player") or {}
    me = players.get(str(own_id)) or players.get(own_id) or {}
    cities = [c for c in (obs.get("city") or {}).values()
              if int(c.get("owner", own_id) or own_id) == own_id]
    units = [u for u in (obs.get("unit") or {}).values()
             if int(u.get("owner", own_id) or own_id) == own_id]
    return {"счёт": me.get("score"), "городов": len(cities), "юнитов": len(units),
            "наблюдение_пустое": not bool(obs)}


def play(port: int, seed: int, turns: int, fps: int, decide: Callable[..., Any],
         overview: bool = False, fog: Optional[bool] = None) -> dict[str, Any]:
    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402
    from civrealm.freeciv.utils.freeciv_logging import log_dir  # noqa: E402

    fog = V.FOG if fog is None else fog
    fc_args["client_port"] = port
    fc_args["debug.take_screenshot"] = True
    fc_args["debug.headless"] = True
    fc_args["debug.global_view_screenshot"] = not fog
    shots_root = Path(log_dir) / "screenshots"
    ov_dir = (shots_root.parent / "overview" / f"port{port}") if overview else None
    before = set(shots_root.rglob("*.png")) if shots_root.exists() else set()

    env = gymnasium.make("civrealm/FreecivBase-v0")
    V.install_signal_handlers()
    obs, info = env.reset(client_port=port, seed=seed)
    V._ACTIVE["env"] = env
    V.start_ui_hiding(env, ov_dir)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0
    states: dict[str, tuple[list[str], list[str]]] = {}
    step_guard = V.install_step_timeout(float(os.environ.get("V011_STEP_TIMEOUT", "30")))
    played = decisions = 0
    outcome, broken = "партия_окончена", False

    def capture(o: dict, turn: Any) -> None:
        for p in V.frames_since(before | set(states), shots_root):
            if p.name in states:
                continue
            left, right = V.state_lines(o or {}, turn, own_id)
            states[p.name] = (left, right)

    try:
        for _ in range(turns):
            for _ in range(V.MAX_DECISIONS_PER_TURN):
                action = decide(obs, info, own_id)
                if action is None:
                    break
                decisions += 1
                with step_guard():
                    obs, _r, terminated, truncated, info = env.step(action)
                capture(obs, (info or {}).get("turn"))
                if terminated or truncated:
                    break
            if not obs:
                outcome, broken = "обрыв", True      # мир отдал {} при серверной проблеме
                break
            with step_guard():
                obs, _r, terminated, truncated, info = env.step(None)
            capture(obs, (info or {}).get("turn"))
            played += 1
            if terminated or truncated:
                break
    except V.StepTimeout:
        print("  [клин] шаг не вернулся — партия прервана", flush=True)
        outcome = "обрыв_шага"
    finally:
        V.cleanup_env(env)
        V._ACTIVE["env"] = None

    frames = V.frames_since(before, shots_root)
    frames = V.draw_state(frames, states, ROOT / "knowledge" / "frames_text" / f"port{port}")
    if os.environ.get("V011_STATE_TEXT", "1") == "1" and states:
        last = list(states.values())[-1]
        print("  [текст на кадре] города: " + " | ".join(last[0][:12]), flush=True)
        print("  [текст на кадре] юниты: " + " | ".join(last[1][:8]), flush=True)
    out = ROOT / "knowledge" / V.video_name(seed, port, ext="mp4")
    ok = V.to_video(frames, out, fps)
    print(f"  кадров {len(frames)} → {'видео ' + str(out) if ok else 'PNG в ' + str(shots_root)}",
          flush=True)
    result = {"сид": seed, "порт": port, "ходов_сыграно": played, "решений": decisions,
              "кадров": len(frames), "видео": str(out) if ok else None,
              "итог": outcome, "туман": bool(fog), "обрыв_связи": broken}
    result.update(_obs_state(obs, own_id))
    return result


def decide(obs, info, own_id):  # noqa: ANN001, ANN201
    """Точка проводки живого агента `v0.11`. По умолчанию — закрыть ход (`None`)."""
    return None


def main() -> int:
    a = _args()
    print(f"[запись] туман: {'наш вид агента' if (V.FOG and not a['no_fog']) else 'наблюдатель'}; "
          f"окно {V.WINDOW}; метка {V.RUN_TAG or '—'}", flush=True)
    r = play(a["port"], a["seed"], a["turns"], a["fps"], decide,
             overview=bool(a["overview"]), fog=None if not a["no_fog"] else False)
    print(json.dumps(r, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
