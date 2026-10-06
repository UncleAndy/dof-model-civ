"""Запись игры в видео под `v0.11` — порт механизма из ветки `v2` (§10.79–10.87).

**Что делает мир, а что мы.** CivRealm **видео не пишет** — он снимает **кадры**
(`debug.take_screenshot`): поднимает headless-браузер (Selenium + Firefox), заходит в партию
наблюдателем и кладёт PNG в `civrealm/logs/screenshots/<пользователь>_<порт>_<дата>/turn_NNN_step_NNNN.png`.
Сборка видео — наша (ffmpeg). Этот модуль — наша часть и ничего не знает о модели: он принимает
готовый `env` и словарь состояний, поэтому один и тот же для `v2` и `v0.11`.

**Грабли, перенесённые как правила (найдены на живом клиенте в `v2`, проверены там же):**

1. `ffmpeg` может не попасть в `PATH` процесса — искать и по nix-хранилищу.
2. `ffmpeg` разрешает **относительные** пути в списке кадров **от каталога списка**, а не от cwd ⇒
   в списке обязаны стоять абсолютные пути.
3. Снимок **элемента** (`element.screenshot()`) в этом браузере падает ⇒ берётся снимок страницы и
   область **вырезается** по координатам.
4. Окна сообщений и диалоги перекрывают карту ⇒ инъекция CSS в **наш** браузер съёмки (стенд не
   трогаем: штатная правка CivRealm правит образ, а образ — владельца).
5. Кадры и любые вспомогательные снимки снимаются с разной частотой ⇒ пары подбираются по
   **близости времени** (mtime), а не по номеру.
6. Браузер съёмки надо **закрывать** (и по SIGTERM тоже): измерено в `v2` — 18 утёкших Firefox,
   каждый 20–50 % CPU.
7. Занятый/залежавшийся порт стенда даёт `AssertionError` в `handle_conn_info` или
   «Connection could not be established» ⇒ для съёмки берётся свежий порт.

**Туман.** Наблюдатель входит командой `/observe` без имени и видит **всю** карту без тумана; наш
собственный вид — `/observe <имя игрока>` — туман уважает (`debug.global_view_screenshot = False`).
Снимать надо от лица агента: иначе в кадре видно то, чего агент не знает.
"""
from __future__ import annotations

import glob
import io
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

#: Что скрываем в браузере съёмки, чтобы окна не перекрывали карту.
HIDE_CSS = """
#game_chatbox_panel, .chatbox_dialog, .ui-dialog, .ui-widget-overlay,
#dialog, #city_dialog, #tech_dialog, #diplomacy_dialog, #messages_panel,
#pregame_text_input, #game_dialog, #nation_dialog, #spacer_dialog,
#units_dialog, #report_dialog { display: none !important; }
"""

#: Размер окна съёмки: чем больше окно, тем больше карты в кадре (нужен общий план). Ширина карты
#: 78 клеток — 2560x1440 показывает почти всю.
WINDOW = os.environ.get("V011_WINDOW", os.environ.get("V2_WINDOW", "2560x1440"))

#: Туман: снимать от лица агента (видно только то, что он видит). `0` — наблюдатель, вся карта.
FOG = os.environ.get("V011_FOG", os.environ.get("V2_FOG", "1")) == "1"

#: Предел решений на один ход — ПРЕДОХРАНИТЕЛЬ, а не политика.
MAX_DECISIONS_PER_TURN = 400

#: Метка прогона: каждой записи своё имя (правило владельца модели), иначе файлы затирают друг друга.
RUN_TAG = os.environ.get("DOF_RUN_TAG", "")


def video_name(seed: Any, port: Any, tag: Optional[str] = None, ext: str = "mp4") -> str:
    """Имя файла записи: сид, порт и метка прогона — чтобы попытки не затирали друг друга."""
    t = RUN_TAG if tag is None else tag
    tail = f"_{t}" if t else ""
    return f"game_{seed}_port{port}{tail}.{ext}"


#: Действующий env — нужен, чтобы по сигналу закрыть браузер съёмки (иначе Firefox остаётся висеть).
_ACTIVE: dict[str, Any] = {"env": None}


def start_ui_hiding(env: Any, overview_dir: Optional[Path] = None,
                    window: Optional[str] = None) -> None:
    """Прятать окна сообщений в браузере съёмки и держать камеру на нашем виде.

    Отдельным потоком, потому что драйвер наблюдения появляется не сразу после `reset`: до него
    инъекция некуда применить. Драйвер закрывается в `cleanup_env`.
    """
    import threading
    import time

    if overview_dir is not None:
        overview_dir.mkdir(parents=True, exist_ok=True)
    win = window or WINDOW
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
                        w, h = (int(x) for x in win.lower().split("x"))
                        driver.set_window_size(w, h)
                        print(f"  [съёмка] окно {w}x{h}", flush=True)
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    # Инъекция НАШЕГО CSS в НАШ браузер съёмки (свойство innerHTML здесь безопасно:
                    # это константа HIDE_CSS из этого файла, а не данные из мира или сети).
                    driver.execute_script(
                        "var s=document.getElementById('dof_hide_ui');"
                        "if(!s){s=document.createElement('style');s.id='dof_hide_ui';"
                        "document.head.appendChild(s);}s.innerHTML=arguments[0];", HIDE_CSS)
                    driver.execute_script(
                        "document.querySelectorAll('.ui-widget-overlay')"
                        ".forEach(function(d){d.style.display='none';});"
                        "['game_chatbox_panel','messages_panel'].forEach(function(id){"
                        "var e=document.getElementById(id);if(e){e.style.display='none';}});")
                    if FOG:
                        # Камера на НАШ юнит: в кадре именно та область, которую агент открыл.
                        # Камера на центре карты даёт почти чёрный кадр — открытый пятачок лежит
                        # в стороне от центра (проверено в `v2`).
                        driver.execute_script(
                            "try{var u=Object.entries(units);"
                            "if(u.length){center_tile_mapcanvas(tiles[u[0][1].tile]);}}catch(e){}")
                    if overview_dir is not None:
                        try:
                            # Снимок ЭЛЕМЕНТА падает ⇒ снимок страницы и вырезка области.
                            from PIL import Image
                            from selenium.webdriver.common.by import By
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
                                print(f"  [съёмка] обзор вне кадра: {loc} {size}", flush=True)
                                said_capture = True
                        except Exception as exc:  # noqa: BLE001
                            if not said_capture:
                                print("  [съёмка] обзор НЕ снят:", type(exc).__name__,
                                      str(exc)[:120], flush=True)
                                said_capture = True
                except Exception:  # noqa: BLE001
                    pass
            if said_driver and driver is None:
                return                      # партия кончилась — поток выходит сам
            time.sleep(1.5)

    threading.Thread(target=loop, daemon=True).start()


def kill_headless_firefox() -> int:
    """Убить оставшиеся съёмочные браузеры (marionette + headless) — последняя линия уборки.

    Нужна потому, что `driver.quit()` доступен не всегда: если партия упала до появления драйвера
    наблюдения, браузер остаётся и ест 20–50 % CPU. Себя и родителей не трогаем.
    """
    import time
    self_pids = {os.getpid(), os.getppid()}

    def leaked() -> list[int]:
        out: list[int] = []
        for d in Path("/proc").iterdir():
            if not d.name.isdigit():
                continue
            pid = int(d.name)
            if pid in self_pids:
                continue
            try:
                cmd = (d / "cmdline").read_bytes().decode("utf-8", "replace")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if "marionette" in cmd and "headless" in cmd:
                out.append(pid)
        return out

    found = leaked()
    for pid in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    if found:
        time.sleep(3)
    for pid in leaked():
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return len(found)


def cleanup_env(env: Any) -> None:
    """Закрыть наблюдение и БРАУЗЕР съёмки. Без этого процессы копятся."""
    if env is None:
        return
    try:
        base = getattr(env, "unwrapped", env)
        ctrl = getattr(base, "civ_controller", None)
        mon = getattr(ctrl, "monitor", None) if ctrl is not None else None
        if mon is not None:
            for step in ("stop_monitor",):
                try:
                    getattr(mon, step)()
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
    # Последняя линия: драйвер доступен не всегда (падение до его появления) — убираем по факту
    # процесса, иначе Firefox остаётся и ест 20–50 % CPU.
    kill_headless_firefox()


def install_signal_handlers() -> None:
    """По SIGTERM/SIGINT закрыть браузер съёмки, а не оставить его висеть."""
    def _on_terminate(sig, _frm):  # noqa: ANN001
        print(f"  [съёмка] сигнал {sig}: закрываю браузер и выхожу", flush=True)
        cleanup_env(_ACTIVE.get("env"))
        os._exit(143)

    signal.signal(signal.SIGTERM, _on_terminate)
    signal.signal(signal.SIGINT, _on_terminate)


class StepTimeout(Exception):
    """Шаг не вернулся за отпущенное время: партию прерываем, а не ждём вечно."""


def install_step_timeout(seconds: float) -> Callable[[], Any]:
    """Таймер шага: `with step_timeout(): env.step(...)`."""
    import contextlib

    @contextlib.contextmanager
    def guard():
        def _on_alarm(_sig, _frm):
            raise StepTimeout()

        old = signal.signal(signal.SIGALRM, _on_alarm)
        signal.setitimer(signal.ITIMER_REAL, float(seconds))
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)

    return guard


def frames_since(before: set, shots_root: Path) -> list[Path]:
    """Новые кадры с момента `before` (мир кладёт их сам)."""
    now = set(shots_root.rglob("*.png")) if shots_root.exists() else set()
    return sorted(now - before)


def font(size: int):
    """Мелкий моноширинный шрифт (DejaVu Sans Mono) — числа выравниваются по колонкам."""
    from PIL import ImageFont
    for pat in ("/nix/store/*dejavu-fonts*/share/fonts/truetype/DejaVuSansMono.ttf",
                "/nix/store/*dejavu-fonts*/share/fonts/truetype/DejaVuSans.ttf",
                "/usr/share/fonts/**/DejaVuSansMono.ttf"):
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            try:
                return ImageFont.truetype(hits[0], size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def counts(items: Sequence[str]) -> list[tuple[str, int]]:
    """Свернуть повторы: [Warriors, Warriors, Explorer] → [(Warriors,2), (Explorer,1)].

    Иначе список юнитов в городе занимает пол-экрана.
    """
    seen: dict[str, int] = {}
    for x in items:
        seen[x] = seen.get(x, 0) + 1
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))


def state_lines(obs: Mapping[str, Any], turn: Any, own_id: Any = 0,
                dof_lookup: Optional[Callable[[str], Optional[float]]] = None,
                index: Optional[float] = None,
                build_names: Optional[Mapping[str, str]] = None) -> tuple[list[str], list[str]]:
    """Текст состояния: СЛЕВА города, СПРАВА юниты. Только то, что публикует мир и что посчитано.

    `dof_lookup` — счёт действий сущности (его даёт извлекатель `v0.11`), `build_names` — что агент
    сам записал как стройку: мир публикует только код, и «код4» читать нельзя.
    """
    obs = obs or {}
    own = int(own_id or 0)
    cities = [c for c in (obs.get("city") or {}).values()
              if int(c.get("owner", own) or own) == own]
    units = [u for u in (obs.get("unit") or {}).values()
             if int(u.get("owner", own) or own) == own]
    left = [f"ХОД {turn}"]
    if isinstance(index, (int, float)):
        left.append(f"индекс {index:.2f}")
    left.append(f"ГОРОДА: {len(cities)}")
    # Кто стоит В ГОРОДЕ: в Freeciv «внутри» города — это его клетка (сопоставляем по координатам;
    # `home_city` означает «город содержит юнита», это другое).
    by_tile: dict[tuple, list[str]] = {}
    for u in units:
        by_tile.setdefault((u.get("x"), u.get("y")), []).append(str(u.get("type_rule_name") or "?"))
    for c in sorted(cities, key=lambda x: str(x.get("name"))):
        cid = str(c.get("id"))
        left.append(f"{c.get('name') or cid} р{c.get('size')}")
        prod = c.get("production_kind")
        eta = c.get("turns_to_prod_complete")
        pname = (build_names or {}).get(cid) or f"код{prod}"
        # 32767 (и вообще огромные значения) — это «никогда», а не число ходов: мир считает так,
        # когда ЧИСТЫЙ приход щитов ≤ 0. Показываем ПРИЧИНУ, а не только «неизвестно».
        eta_txt = f"за {eta}х" if isinstance(eta, int) and 0 < eta < 1000 else "срок неизвестен"
        if eta_txt == "срок неизвестен":
            gross, net = c.get("prod_shield"), c.get("surplus_shield")
            waste = c.get("city_waste") or 0
            if isinstance(net, (int, float)) and isinstance(gross, (int, float)) \
                    and gross > 0 and net <= 0:
                why = "содержание юнитов" if not waste else f"потери {waste:g}"
                eta_txt = f"НЕ ИДЁТ: щиты {gross:.0f}→{net:.0f} ({why})"
        left.append(f"  стройка {pname} {eta_txt}")
        gross_s, net_s = c.get("prod_shield"), c.get("surplus_shield")
        sh_txt = (f"щит{net_s:.0f}/{gross_s:.0f}"
                  if isinstance(net_s, (int, float)) and isinstance(gross_s, (int, float))
                  else f"щит{gross_s}")
        left.append(f"  еда{c.get('surplus_food')} {sh_txt} наука{c.get('science')}")
        d = dof_lookup(f"city:{cid}") if dof_lookup else None
        left.append(f"  действий {float(d):.0f}" if isinstance(d, (int, float)) else "  действий —")
        imps = list(c.get("improvements_present") or [])
        left.append("  постройки:")
        if imps:
            for nm, cnt in counts([str(x) for x in imps]):
                left.append(f"    {nm}" + (f" x {cnt}" if cnt > 1 else ""))
        else:
            left.append("    —")
        here = by_tile.get((c.get("x"), c.get("y"))) or []
        left.append("  в городе:")
        if here:
            for nm, cnt in counts(here):
                left.append(f"    {nm}" + (f" x {cnt}" if cnt > 1 else ""))
        else:
            left.append("    —")
    # Правая колонка — ТОЛЬКО свои юниты: мир отдаёт в `unit` своих, а чужие видны лишь через
    # карту (`map.unit_owner`), поэтому фильтр по владельцу обязателен, а не косметичен.
    own_pairs: list[tuple[str, Mapping[str, Any]]] = [
        (str(k), u) for k, u in (obs.get("unit") or {}).items()
        if isinstance(u, Mapping) and int(u.get("owner", own) or own) == own]
    right = ["ЮНИТЫ: " + str(len(own_pairs))]
    ulines: list[str] = []
    for key, u in own_pairs:
        t = str(u.get("type_rule_name") or "?")
        d = dof_lookup(f"unit:{key}") if dof_lookup else None
        d_txt = f"д{float(d):.0f}" if isinstance(d, (int, float)) else "д—"
        ulines.append(f"{t} HP{u.get('health')} ход{u.get('moves_left')} "
                      f"({u.get('x')},{u.get('y')}) {d_txt}")
    for line, cnt in counts(ulines):
        right.append(line + (f" x {cnt}" if cnt > 1 else ""))
    return left, right


def clip(text: str, fnt, max_w: int) -> str:
    """Обрезать строку по ШИРИНЕ: колонка не должна занимать больше трети кадра."""
    if fnt.getlength(text) <= max_w:
        return text
    while text and fnt.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


def draw_state(frames: Sequence[Path], states: Mapping[str, tuple[list[str], list[str]]],
               out_dir: Path) -> list[Path]:
    """Нанести текст состояния на кадры: города слева, юниты справа.

    Контраст без заливки: светлые глифы с тёмной обводкой — читаемо и на тёмном, и на светлом фоне,
    панель не рисуется, чтобы не закрывать карту.
    """
    if not frames or not states:
        return list(frames)
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
            size = max(11, img.width // 170)
            fnt = font(size)
            lh = size + 3
            margin = 3 * lh
            max_w = int(img.width / 3) - 2 * margin
            left, right = st
            y = margin
            for line in left:
                draw.text((margin, y), clip(line, fnt, max_w), font=fnt,
                          fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
                y += lh
                if y > img.height - lh:
                    break
            y = margin
            for line in right:
                txt = clip(line, fnt, max_w)
                w = fnt.getlength(txt)
                draw.text((img.width - margin - w, y), txt, font=fnt,
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


def ffmpeg_path() -> Optional[str]:
    """`ffmpeg` может не попасть в PATH процесса: искать и по nix-хранилищу."""
    p = shutil.which("ffmpeg")
    if p:
        return p
    for pat in ("/nix/store/*-ffmpeg-*/bin/ffmpeg", "/nix/store/*-ffmpeg-full-*/bin/ffmpeg"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def frame_list_text(frames: Sequence[Path], fps: int) -> str:
    """Список кадров для ffmpeg. Пути — АБСОЛЮТНЫЕ: относительные ffmpeg разрешает от каталога
    списка, а не от cwd (проверено в `v2`)."""
    return "".join(f"file '{f.resolve()}'\nduration {1.0 / max(1, fps):.4f}\n" for f in frames)


def to_video(frames: Sequence[Path], out: Path, fps: int = 6) -> bool:
    """Собрать mp4 из кадров. Нет кадров или нет ffmpeg — честный отказ, кадры остаются PNG."""
    if not frames:
        return False
    ff = ffmpeg_path()
    if ff is None:
        print("  ffmpeg не найден — кадры остались как PNG", flush=True)
        return False
    listfile = out.with_suffix(".txt")
    listfile.write_text(frame_list_text(frames, fps))
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
           "-vsync", "vfr", "-pix_fmt", "yuv420p",
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        print("  ffmpeg не запустился:", str(exc)[:140], flush=True)
        return False
    if r.returncode != 0:
        tail = r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else "без сообщения"
        print("  ffmpeg вернул ошибку:", tail, flush=True)
        return False
    return True
