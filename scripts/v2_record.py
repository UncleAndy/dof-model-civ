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
import io
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

from PIL import Image  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402

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

#: Что скрываем в браузере съёмки, чтобы окна сообщений не перекрывали карту.
#: Это тот же смысл, что у штатной правки CivRealm (`build_server.py:
#: update_javascript_for_clean_screenshot` — там авто-открытие окон закомментировано в JS клиента),
#: но делается в НАШЕМ браузере: стенд не трогаем (docker недоступен и это стенд пользователя).
#: ВАЖНО (измерено): правило `.ui-dialog` прятать НЕЛЬЗЯ — в этом контейнере лежит и обзорная
#: карта, из-за чего она получала размер 0x0 и «вся карта» пропадала. Прячем только окна сообщений.
HIDE_CSS = """
#game_chatbox_panel, .chatbox_dialog, .ui-widget-overlay,
#dialog, #city_dialog, #tech_dialog, #diplomacy_dialog, #messages_panel,
#pregame_text_input, #game_dialog, #nation_dialog, #spacer_dialog,
#units_dialog, #report_dialog { display: none !important; }
"""


def _start_ui_hiding(env, overview_dir: Optional[Path] = None) -> None:
    """Прятать окна и снимать ОБЗОРНУЮ карту (вся карта) для вклейки в кадр.

    Смысл тот же, что у штатной правки CivRealm, но в НАШЕМ браузере: стенд не трогаем.
    Обзорная карта клиента (`#overview_map`) показывает ВСЮ карту — её и вклеиваем в угол кадра,
    иначе в кадре виден только небольшой кусок (замечание Andy).
    """
    import threading
    import time

    if overview_dir is not None:
        overview_dir.mkdir(parents=True, exist_ok=True)
    shot_no = 0

    def loop() -> None:
        nonlocal shot_no
        said_driver = False
        said_capture = False
        for _ in range(6000):
            driver = None
            try:
                mon = getattr(env.unwrapped.civ_controller, "monitor", None)
                driver = getattr(mon, "_driver", None) if mon is not None else None
            except Exception:  # noqa: BLE001
                driver = None
            if driver is not None:
                if not said_driver:
                    print("  [съёмка] драйвер наблюдения получен", flush=True)
                    said_driver = True
                try:
                    driver.execute_script(
                        "var s=document.getElementById('hermes_hide_ui');"
                        "if(!s){s=document.createElement('style');s.id='hermes_hide_ui';"
                        "document.head.appendChild(s);}s.innerHTML=arguments[0];", HIDE_CSS)
                    driver.execute_script(
                        "document.querySelectorAll('.ui-widget-overlay')"
                        ".forEach(function(d){d.style.display='none';});"
                        "['game_chatbox_panel','messages_panel'].forEach(function(id){"
                        "var e=document.getElementById(id);if(e){e.style.display='none';}});")
                    # обзорная карта: показать ВМЕСТЕ С РОДИТЕЛЯМИ (её контейнер — .ui-dialog,
                    # который мы больше не скрываем) и перерисовать
                    driver.execute_script(
                        "try{var o=document.getElementById('overview_map');"
                        "if(o){var n=o;while(n&&n.style){n.style.display='block';"
                        "n.style.visibility='visible';n=n.parentElement;}}}catch(e){}"
                        "try{if(typeof redraw_overview==='function'){redraw_overview();}}catch(e){}")
                    if overview_dir is not None:
                        try:
                            # Снимок ЭЛЕМЕНТА в этом браузере падает (WebDriverException),
                            # поэтому берём снимок страницы и ВЫРЕЗАЕМ область обзора.
                            el = driver.find_element(By.ID, "overview_map")
                            loc, size = el.location, el.size
                            raw = driver.get_screenshot_as_png()
                            img = Image.open(io.BytesIO(raw))
                            x0 = max(0, int(loc["x"]))
                            y0 = max(0, int(loc["y"]))
                            x1 = min(img.width, x0 + int(size["width"]))
                            y1 = min(img.height, y0 + int(size["height"]))
                            if x1 - x0 > 20 and y1 - y0 > 20:
                                shot_no += 1
                                img.crop((x0, y0, x1, y1)).save(
                                    str(overview_dir / f"ov_{shot_no:05d}.png"))
                                if not said_capture:
                                    print(f"  [съёмка] обзор снят {x1 - x0}x{y1 - y0}", flush=True)
                                    said_capture = True
                            elif not said_capture:
                                print(f"  [съёмка] область обзора вне кадра: {loc} {size}",
                                      flush=True)
                                said_capture = True
                        except Exception as exc:  # noqa: BLE001
                            if not said_capture:
                                print("  [съёмка] обзор НЕ снят:", type(exc).__name__,
                                      str(exc)[:120], flush=True)
                                said_capture = True
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(1.5)

    threading.Thread(target=loop, daemon=True).start()


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


def _composite(frames: list[Path], ov_dir: Optional[Path], out_dir: Path) -> list[Path]:
    """Вклеить ОБЗОРНУЮ карту (вся карта) в угол каждого кадра.

    Кадры и обзорные снимки снимаются с разной частотой, поэтому пара подбирается по БЛИЗОСТИ ВО
    ВРЕМЕНИ (по mtime), а не по номеру: иначе в кадр попадала бы обзорная карта другого хода.
    """
    if ov_dir is None or not ov_dir.exists():
        return frames
    ovs = sorted(ov_dir.glob("*.png"))
    if not ovs:
        return frames
    from PIL import Image
    ov_t = [(p, p.stat().st_mtime) for p in ovs]
    out_dir.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []
    for f in frames:
        try:
            t = f.stat().st_mtime
            ov = min(ov_t, key=lambda pt: abs(pt[1] - t))[0]
            base = Image.open(f).convert("RGB")
            ins = Image.open(ov).convert("RGB")
            w = max(160, int(base.width * 0.30))
            h = max(80, int(ins.height * w / float(ins.width)))
            base.paste(ins.resize((w, h)), (base.width - w - 8, 8))
            dst = out_dir / f.name
            base.save(dst)
            result.append(dst)
        except Exception:  # noqa: BLE001
            result.append(f)
    return result


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
    ov_dir = SHOTS_ROOT.parent / "overview" / f"port{port}"
    obs, info = env.reset(client_port=port, seed=seed)
    _start_ui_hiding(env, ov_dir)   # прячем окна и снимаем обзорную карту (вся карта)
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
    frames = _composite(frames, SHOTS_ROOT.parent / "overview" / f"port{port}",
                        ROOT / "knowledge" / "frames_overlay" / f"port{port}")
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
    fc_args["debug.global_view_screenshot"] = True   # камера на центр карты, а не на один юнит
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