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
#: Прячем ВСЕ окна, включая контейнеры `.ui-dialog`: замечание Andy — окна перекрывают карту.
#: (Обзорную карту в кадр больше не вклеиваем: Andy выбрал вариант БЕЗ оверлея, общим планом.)
HIDE_CSS = """
#game_chatbox_panel, .chatbox_dialog, .ui-dialog, .ui-widget-overlay,
#dialog, #city_dialog, #tech_dialog, #diplomacy_dialog, #messages_panel,
#pregame_text_input, #game_dialog, #nation_dialog, #spacer_dialog,
#units_dialog, #report_dialog { display: none !important; }
"""

#: Размер окна съёмки. Чем больше окно, тем БОЛЬШЕ карты видно в кадре (замечание Andy: нужен
#: общий план, а не детали). Ширина карты — 78 клеток, так что 2560x1440 показывает почти всю.
WINDOW = os.environ.get("V2_WINDOW", "2560x1440")

#: ТУМАН: снимать ОТ ЛИЦА нашего агента (видно только то, что он реально видит), а не наблюдателем.
#: Механика (проверено по коду CivRealm): наблюдатель входит командой `/observe` без имени и видит ВСЮ
#: карту без тумана; наш собственный вид — `/observe <имя игрока>` — туман уважает.
#: `V2_FOG=0` возвращает прежний режим (наблюдатель, вся карта открыта).
FOG = os.environ.get("V2_FOG", "1") == "1"


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
                        w, h = (int(x) for x in WINDOW.lower().split("x"))
                        driver.set_window_size(w, h)      # больше окна — больше карты в кадре
                        print(f"  [съёмка] окно {w}x{h}", flush=True)
                    except Exception:  # noqa: BLE001
                        pass
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
                    # обзорная карта: нужна ТОЛЬКО для режима с оверлеем (V2_OVERVIEW=1). Показываем её
                    # вместе с родителями и перерисовываем; иначе не трогаем (её контейнер скрыт).
                    if overview_dir is not None:
                        driver.execute_script(
                            "try{var o=document.getElementById('overview_map');"
                            "if(o){var n=o;while(n&&n.style){n.style.display='block';"
                            "n.style.visibility='visible';n=n.parentElement;}}}catch(e){}"
                            "try{if(typeof redraw_overview==='function'){redraw_overview();}}catch(e){}")
                    if FOG:
                        # Камера на НАШ ЮНИТ (как штатный локальный вид): в кадре оказывается именно та
                        # область, которую агент открыл, а остальное остаётся тёмным (неизвестным).
                        # Проверено: камера на центре карты даёт почти чёрный кадр (95 %), потому что
                        # открытый агентом пятачок лежит в стороне от центра.
                        driver.execute_script(
                            "try{var u=Object.entries(units);"
                            "if(u.length){center_tile_mapcanvas(tiles[u[0][1].tile]);}}catch(e){}")
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


#: Действующий env — нужен, чтобы при SIGTERM закрыть браузер съёмки (иначе Firefox остаётся
#: висеть и грузит процессор: измерено — 18 таких утечек, каждая 20–50 % CPU).
_ACTIVE: dict = {"env": None}


def _cleanup_env(env) -> None:
    """Закрыть наблюдение и БРАУЗЕР съёмки. Без этого процессы копятся."""
    if env is None:
        return
    try:
        base = getattr(env, "unwrapped", env)
        ctrl = getattr(base, "civ_controller", None)
        mon = getattr(ctrl, "monitor", None) if ctrl is not None else None
        if mon is not None:
            try:
                mon.stop_monitor()
            except Exception:  # noqa: BLE001
                pass
            drv = getattr(mon, "_driver", None)
            if drv is not None:
                try:
                    drv.quit()
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass


def _on_terminate(sig, _frm):  # noqa: ANN001
    print(f"  [съёмка] сигнал {sig}: закрываю браузер и выхожу", flush=True)
    _cleanup_env(_ACTIVE.get("env"))
    os._exit(143)


signal.signal(signal.SIGTERM, _on_terminate)
signal.signal(signal.SIGINT, _on_terminate)


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


def _font(size: int):
    """Мелкий моноширинный шрифт (DejaVu Sans Mono) — числа выравниваются по колонкам."""
    import glob
    from PIL import ImageFont
    for pat in ("/nix/store/*dejavu-fonts*/share/fonts/truetype/DejaVuSansMono.ttf",
                "/nix/store/*dejavu-fonts*/share/fonts/truetype/DejaVuSans.ttf"):
        hits = sorted(glob.glob(pat))
        if hits:
            try:
                return ImageFont.truetype(hits[0], size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _counts(items: list[str]) -> list[tuple[str, int]]:
    """Свернуть повторы: [Warriors, Warriors, Explorer] → [(Explorer,1), (Warriors,2)].

    Повторяющиеся типы помечаются как «x N» — иначе список юнитов в городе занимает пол-экрана.
    """
    seen: dict[str, int] = {}
    for x in items:
        seen[x] = seen.get(x, 0) + 1
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))


def _state_lines(obs: dict, turn, own_id: int, graph, index) -> tuple[list[str], list[str]]:
    """Текст состояния: СЛЕВА города, СПРАВА юниты. Только то, что публикует мир и что посчитано."""
    obs = obs or {}
    cities = [c for c in (obs.get("city") or {}).values() if c.get("owner") == own_id]
    units = [u for u in (obs.get("unit") or {}).values() if u.get("owner") == own_id]
    left = [f"ХОД {turn}"]
    if isinstance(index, (int, float)):
        left.append(f"индекс {index:.2f}")
    left.append(f"ГОРОДА: {len(cities)}")
    # Кто стоит В ГОРОДЕ: в Freeciv «внутри» города — это его клетка. Сопоставляем по координатам
    # (поле `home_city` означает «город содержит юнита», это другое).
    by_tile: dict[tuple, list[str]] = {}
    for u in units:
        by_tile.setdefault((u.get("x"), u.get("y")), []).append(
            str(u.get("type_rule_name") or "?"))
    for c in sorted(cities, key=lambda x: str(x.get("name"))):
        cid = str(c.get("id"))
        name = str(c.get("name") or cid)
        left.append(f"{name} р{c.get('size')}")
        prod = c.get("production_kind")
        eta = c.get("turns_to_prod_complete")
        e = graph.entity(f"city:{cid}") if graph is not None else None
        # Название стройки: мир публикует только код, поэтому берём то, что агент сам записал.
        pname = (e.attrs.get("стройка") if e is not None else None) or f"код{prod}"
        # 32767 (и вообще огромные значения) — это «никогда», а не число ходов. Мир считает так
        # (`city_turns_to_build`), когда ЧИСТЫЙ приход щитов ≤ 0: тогда постройка не движется
        # вообще. Показываем ПРИЧИНУ, а не только «неизвестно».
        eta_txt = f"за {eta}х" if isinstance(eta, int) and 0 < eta < 1000 else "срок неизвестен"
        if eta_txt == "срок неизвестен":
            gross = c.get("prod_shield")
            net = c.get("surplus_shield")
            waste = c.get("city_waste") or 0
            if isinstance(net, (int, float)) and isinstance(gross, (int, float)) and gross > 0 \
                    and net <= 0:
                why = "содержание юнитов" if not waste else f"потери {waste:g}"
                eta_txt = f"НЕ ИДЁТ: щиты {gross:.0f}→{net:.0f} ({why})"
        left.append(f"  стройка {pname} {eta_txt}")
        gross_s = c.get("prod_shield")
        net_s = c.get("surplus_shield")
        sh_txt = (f"щит{net_s:.0f}/{gross_s:.0f}" if isinstance(net_s, (int, float))
                  and isinstance(gross_s, (int, float)) else f"щит{gross_s}")
        left.append(f"  еда{c.get('surplus_food')} {sh_txt} наука{c.get('science')}")
        d = getattr(getattr(e, "dof", None), "v", None) if e is not None else None
        d_txt = f"{float(d):.0f}" if isinstance(d, (int, float)) else "—"
        left.append(f"  действий {d_txt}")
        # ПОСТРОЙКИ: вертикальным списком (имена восстановлены из вектора `improvements`).
        imps = list(e.attrs.get("improvements_present") or []) if e is not None else []
        left.append("  постройки:")
        if imps:
            for nm, cnt in _counts(imps):
                left.append(f"    {nm}" + (f" x {cnt}" if cnt > 1 else ""))
        else:
            left.append("    —")
        # ЮНИТЫ В ГОРОДЕ — вертикальным списком, только имена, повторы как «x N».
        here = by_tile.get((c.get("x"), c.get("y"))) or []
        left.append("  в городе:")
        if here:
            for nm, cnt in _counts(here):
                left.append(f"    {nm}" + (f" x {cnt}" if cnt > 1 else ""))
        else:
            left.append("    —")
    # ЮНИТЫ — справа: одна строка на юнита; ОДИНАКОВЫЕ строки сворачиваются как «x N».
    right = ["ЮНИТЫ: " + str(len(units))]
    ulines: list[str] = []
    for u in units:
        uid = None
        for k, v in (obs.get("unit") or {}).items():
            if v is u:
                uid = str(k)
                break
        t = str(u.get("type_rule_name") or "?")
        e = graph.entity(f"unit:{uid}") if (graph is not None and uid) else None
        d = getattr(getattr(e, "dof", None), "v", None) if e is not None else None
        d_txt = f"д{float(d):.0f}" if isinstance(d, (int, float)) else "д—"
        fort = " УКР" if (e is not None and e.attrs.get("наш_укреплён")) else ""
        ulines.append(f"{t} HP{u.get('health')} ход{u.get('moves_left')} "
                      f"({u.get('x')},{u.get('y')}) {d_txt}{fort}")
    for line, cnt in _counts(ulines):
        right.append(line + (f" x {cnt}" if cnt > 1 else ""))
    return left, right


def _clip(text: str, font, max_w: int) -> str:
    """Обрезать строку по ШИРИНЕ (колонка не должна занимать больше трети кадра)."""
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


def _draw_state(frames: list[Path], states: dict, out_dir: Path) -> list[Path]:
    """Нанести текст состояния на кадры: города слева, юниты справа.

    Контраст без заливки: светлые глифы с ТЁМНОЙ обводкой — читаемо и на тёмном, и на светлом фоне
    (панель не рисуем, чтобы не закрывать карту). Колонка ≤ 1/3 ширины кадра, по высоте — сколько есть.
    """
    if not frames or not states:
        return frames
    from PIL import Image, ImageDraw
    out_dir.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []
    for f in frames:
        st = states.get(f.name)
        if not st:
            result.append(f)
            continue
        try:
            img = Image.open(f).convert("RGB")
            draw = ImageDraw.Draw(img)
            size = max(11, img.width // 170)          # мелкий шрифт
            font = _font(size)
            lh = size + 3
            margin = 3 * lh                             # отступ ≈ 3 строки текста (сверху, слева, справа)
            max_w = int(img.width / 3) - 2 * margin   # колонка ≤ 1/3 ширины, с запасом по краям
            left, right = st
            y = margin
            for line in left:                          # ГОРОДА — слева
                draw.text((margin, y), _clip(line, font, max_w), font=font,
                          fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
                y += lh
                if y > img.height - lh:
                    break
            y = margin
            for line in right:                         # ЮНИТЫ — справа
                txt = _clip(line, font, max_w)
                w = font.getlength(txt)
                draw.text((img.width - margin - w, y), txt, font=font,
                          fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
                y += lh
                if y > img.height - lh:
                    break
            dst = out_dir / f.name
            img.save(dst)
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
    ov_dir = (SHOTS_ROOT.parent / "overview" / f"port{port}"
              if os.environ.get("V2_OVERVIEW") == "1" else None)
    obs, info = env.reset(client_port=port, seed=seed)
    _ACTIVE["env"] = env
    _start_ui_hiding(env, ov_dir)   # прячем окна (и, если просили, снимаем обзорную карту)
    try:
        own_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        own_id = 0
    own_id = own_id or 0
    used: set = set()
    played = actions = 0
    terminated = truncated = False
    # ТЕКСТ СОСТОЯНИЯ НА КАДРЕ: к каждому новому кадру привязываем состояние ИМЕННО этого момента.
    states: dict[str, tuple[list[str], list[str]]] = {}
    seen: set = set()

    def _capture(_obs: dict, _turn) -> None:
        new = [p for p in _frames_since(before | seen) if p.name not in states]
        if not new:
            return
        idx = getattr(agent, "_last_index", None)
        graph = getattr(getattr(agent, "store", None), "graph", None)
        left, right = _state_lines(_obs, _turn, own_id, graph, idx)
        for p in new:
            states[p.name] = (left, right)
            seen.add(p)

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
                _capture(obs, (info or {}).get("turn"))
                if terminated or truncated:
                    break
            if terminated or truncated:
                break
            obs, _r, terminated, truncated, info = step(env, None)
            agent.record_outcome(obs, own_id)
            _capture(obs, (info or {}).get("turn"))
            used.clear()
            played += 1
            if terminated or truncated:
                break
    except StepTimeout:
        print("  [клин] шаг не вернулся — партия прервана", flush=True)
    _cleanup_env(env)
    _ACTIVE["env"] = None

    frames = _frames_since(before)
    frames = _composite(frames, SHOTS_ROOT.parent / "overview" / f"port{port}",
                        ROOT / "knowledge" / "frames_overlay" / f"port{port}")
    if os.environ.get("V2_STATE_TEXT", "1") == "1":
        frames = _draw_state(frames, states, ROOT / "knowledge" / "frames_text" / f"port{port}")
        print(f"  [съёмка] текст состояния нанесён на {len(states)} кадров", flush=True)
        if states:
            _last = list(states.values())[-1]
            print("  [текст на кадре] города (слева): " + " | ".join(_last[0][:14]), flush=True)
            print("  [текст на кадре] юниты (справа): " + " | ".join(_last[1][:8]), flush=True)
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
    fc_args["debug.global_view_screenshot"] = not FOG   # FOG: наш вид (туман), иначе наблюдатель (вся карта)
    print(f"[запись] туман: {'наш вид агента' if FOG else 'наблюдатель (вся карта)'}; окно {WINDOW}")
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