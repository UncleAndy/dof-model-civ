"""Живой прогон `v0.11` на стенде: наблюдение партии + запись видео параллельно.

Один процесс, одна партия: кадры снимает **мир** (headless-браузер, отдельный поток внутри CivRealm),
а мы в это время мерим каждый ход **тем же кодом**, что и прогон на записанных наблюдениях
(`env/spec_obs.measure_step`), и наносим состояние на кадры. Отсюда «параллельная генерация видео»:
кадры идут своим чередом, замер — своим, и видео собирается по окончании.

Что пишется в трассу по каждому ходу: индекс, счёт векторов `V` по сущностям, свои города и юниты,
наблюдённые нападения, метки источников коллапса, строки канала смены производства и цена смены.
Если нападать и менять стройку некому (мирные ходы, аifill играет сам), это видно прямо в трассе —
и ноль **не выглядит** как «опасности нет»: он идёт с причиной.

Запуск (порт занимает стенд — брать свежий и свободный):

    P=$PWD; SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
    PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP" PYTHONWARNINGS=ignore \
    V011_TURNS=80 V011_FPS=6 DOF_RUN_TAG=live1 \
    .venv/bin/python scripts/v011_live_run.py --port 6001 --seed 9200
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env import spec_obs as SO  # noqa: E402
from env import spec_risk as SK  # noqa: E402
from env import video as V  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402


_DEMO = {"n": 0, "dirs": ["goto_4", "goto_6", "goto_3", "goto_1"]}

#: Живой драйвер решений, его состояние по ходу и наблюдение предыдущего вызова.
_DRIVER = None
_LAST_TURN = None
_PREV_OBS = None
#: Откуда пришло действие — эта подпись печатается рядом с решением и не даёт спутать
#: самопроверку записи с поведением модели (однажды уже спутала: `V011_DEMO_MOVE` остался
#: в окружении, и прогон «драйвера» на деле был прогоном самопроверки).
_SOURCE = ["—"]
#: Строки основания печатаются один раз на ход: планирование идёт на каждое решение, а мотив
#: основания — величина хода, и шесть её повторов подряд читаются как шесть разных мотивов.
_FOUNDING_SHOWN: set = set()


def _score_of_world(obs, own_id):  # noqa: ANN001, ANN201
    """Счёт, публикуемый игрой, по нашей стороне — внешняя мера парного опыта (в).

    Процедура одна на проект: `env.spec_drive.world_score`. Импорт отложенный — прогон без живой
    игры не должен тянуть драйвер ради одной величины.
    """
    from env.spec_drive import world_score  # noqa: PLC0415
    return world_score(obs, own_id)


#: Направления игры `goto_N` → смещение клетки. Взято из конфига civrealm
#: (`configs/llm_wrapper_settings.yaml`, 0 NW, 1 N, 2 NE, 3 W, 4 E, 5 SW, 6 S, 7 SE) — проверить здесь,
#: а не помнить: 3 и 4 — это запад и восток, последовательность не круговая.
_SCOUT_DIRS = {0: (-1, -1), 1: (0, -1), 2: (1, -1), 3: (-1, 0),
               4: (1, 0), 5: (-1, 1), 6: (0, 1), 7: (1, 1)}
#: Открытая клетка в `obs["map"]["status"]`; всё прочее (0 — вне обзора, 1) считается нераскрытым.
_OPEN = 2
#: Ходы, в которых разведка уже сделала свой шаг (правило: один шаг за ход).
_SCOUT_DONE_TURNS: set = set()
#: Состояние записи открытий: множество открытых клеток прошлого хода.
_REVEAL: dict = {"set": None, "turn": None}



def _scout_mode() -> str:
    """Объявленный режим оснастки: `idle-only` (приоритет у дела) или `settler-first`."""
    return str(os.environ.get("V011_SCOUT_MODE", "") or "").strip()


def _own_city_count(obs) -> int:  # noqa: ANN001
    """Сколько своих городов в наблюдении — считает оснастка, а не догадка."""
    own = None
    try:
        own = int(os.environ.get("V011_OWN_ID", "0"))
    except Exception:  # noqa: BLE001
        own = 0
    cities = (obs or {}).get("city") or {}
    return sum(1 for c in cities.values()
               if isinstance(c, dict) and int(c.get("owner", -1)) == own)


def _record_reveals(obs, turn, tag) -> None:  # noqa: ANN001, ANN201
    """Записать, что открылось за прошедший ход: клетки и их содержимое по слоям наблюдения."""
    if str(os.environ.get("V011_SCOUT_LOG", "") or "").strip() in ("", "0"):
        return
    m = (obs or {}).get("map") or {}
    status = m.get("status")
    if status is None:
        return
    grid = [[int(v) for v in col] for col in status]
    now = {(x, y) for x, col in enumerate(grid) for y, v in enumerate(col) if v == _OPEN}
    if _REVEAL["turn"] == turn:
        return                      # в этом ходу уже записали — второй раз не считаем
    prev, prev_turn = _REVEAL["set"], _REVEAL["turn"]
    fresh = sorted(now - prev) if prev is not None else []
    _REVEAL["set"], _REVEAL["turn"] = now, turn
    def layer(name):  # noqa: ANN001
        """Слой карты как список столбцов; неразобранный элемент — `None`, а не ноль и не падение."""
        arr = m.get(name)
        if arr is None:
            return None
        out = []
        for col in arr:
            row = []
            for v in col:
                try:
                    row.append(int(v))
                except Exception:  # noqa: BLE001
                    row.append(None)
            out.append(row)
        return out
    layers = {n: layer(n) for n in ("terrain", "extras", "output", "tile_owner",
                                    "city_owner", "unit", "unit_owner")}
    rows = []
    for x, y in fresh:
        item = {"x": x, "y": y}
        for name, arr in layers.items():
            if arr is not None and 0 <= x < len(arr) and 0 <= y < len(arr[x]):
                item[name] = arr[x][y]
        rows.append(item)
    path = ROOT / "knowledge" / f"scout_reveal_{tag or 'none'}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ход": turn, "открыто_всего": len(now), "новых_клеток": len(fresh),
                             "клетки": rows}, ensure_ascii=False) + "\n")
    print(f"    [открытия] ход {turn}: открыто всего {len(now)}, новых {len(fresh)}", flush=True)

def _scout_action(obs, info):  # noqa: ANN001, ANN201
    """Оснастка опыта: шаг к нераскрытой клетке. `(unit, actor, действие)` или `None`.

    Правило объявлено ДО данных: (1) если рядом с юнитом есть нераскрытая клетка — шаг на неё, при
    нескольких — меньший номер направления; (2) иначе шаг, уменьшающий расстояние до ближайшей
    нераскрытой клетки карты; (3) если и такого нет — юнит пропускается. Ничего не подбирается и не
    взвешивается: это разведка, а не политика.
    """
    units = ((info or {}).get("available_actions") or {}).get("unit") or {}
    raw = ((obs or {}).get("map") or {}).get("status")
    if not units or raw is None:
        return None
    # Карта приходит массивом: булево чтение массива запрещено (`ValueError` на `not grid`),
    # поэтому сразу приводим к спискам целых — и вопросы «истинности» снимаются вместе с ним.
    grid = [[int(s) for s in row] for row in raw]
    xsize = len(grid)
    ysize = len(grid[0]) if grid else 0
    # Слои карты имеют форму (xsize, ysize) → первый индекс это x, а не y. Здесь раньше стояло
    # `grid[y][x]` — транспозиция, из-за которой «ближайшая нераскрытая клетка» была не той.
    unseen = [(x, y) for x, col in enumerate(grid) for y, s in enumerate(col) if s != _OPEN]
    if not unseen:
        return None
    for actor in sorted(units):
        names = units.get(actor) or {}
        u = ((obs or {}).get("unit") or {}).get(actor) or {}
        ux, uy = u.get("x"), u.get("y")
        if ux is None or uy is None:
            continue
        here = [(ux + dx, uy + dy) for dx, dy in _SCOUT_DIRS.values()]
        for d in sorted(_SCOUT_DIRS):
            tx, ty = ux + _SCOUT_DIRS[d][0], uy + _SCOUT_DIRS[d][1]
            if tx < 0 or ty < 0 or (xsize and tx >= xsize) or (ysize and ty >= ysize):
                continue
            if 0 <= tx < len(grid) and 0 <= ty < len(grid[tx]) and grid[tx][ty] != _OPEN:
                if f"goto_{d}" in names:
                    return ("unit", actor, f"goto_{d}")
        best = min(unseen, key=lambda c: max(abs(c[0] - ux), abs(c[1] - uy)))
        dx = (best[1] > ux) - (best[1] < ux)
        dy = (best[0] > uy) - (best[0] < uy)
        for d, (ddx, ddy) in _SCOUT_DIRS.items():
            if (ddx, ddy) == (dx, dy) and f"goto_{d}" in names:
                return ("unit", actor, f"goto_{d}")
    return None


def decide(obs, info, own_id):  # noqa: ANN001, ANN201
    """Точка проводки живого агента `v0.11`.

    По умолчанию работает **живой драйвер** (`env.spec_drive.Decider`): он объявляет прирост из
    измерения и отдаёт выбор ядру, а в мир уходит первый шаг выбранного пути. `None` (закрыть ход) —
    законный и ожидаемый итог: ядро берёт действие только при `NetDelta > 0`.

    `V011_DEMO_MOVE=k` включает **САМОПРОВЕРКУ ЗАПИСИ**: раз в `k` решений берётся шаг нашего юнита в
    одном из четырёх направлений по кругу. Это **не поведение модели** и не должно так читаться: так
    проверяется ровно одно — видно ли движение в кадре. Повод прямой: в пассивном прогоне соседние
    кадры различались на **0.01 %** (медиана по 60 кадрам) — владелец модели верно заметил, что на
    видео ничего не происходит, и причина не в записи, а в отсутствии решений.
    """
    global _DRIVER, _LAST_TURN, _PREV_OBS, _SOURCE
    #: Владелец (2026-10-08): вариант с разведкой принят как лучший ВОЛЕВЫМ решением (опыт
    #: эффект не установил — §13.73). Поэтому по умолчанию разведка ВКЛЮЧЕНА: переключатель
    #: читается как «1», если переменная не задана; явные `V011_SCOUT=` (пусто) или `=0`
    #: по-прежнему выключают её — так работают плечи A/B в оснастке опытов.
    _scout_on = str(os.environ.get("V011_SCOUT", "1") or "").strip() not in ("", "0")
    _scout_how = (_scout_mode() or "idle-only")
    # Темп объявлен: один шаг разведки за ход. Иначе на каждый шаг приходится обмен с сервером игры,
    # и мир не успевает за ход (`AssertionError` на `server_timeout_handle`).
    if _scout_on and _scout_how == "settler-first" and _own_city_count(obs) == 0 \
            and (info or {}).get("turn") not in _SCOUT_DONE_TURNS:
        _act = _scout_action(obs, info)
        if _act is not None:
            _SCOUT_DONE_TURNS.add((info or {}).get("turn"))
            _SOURCE[0] = "РАЗВЕДКА РАДИ ОСНОВАНИЯ (оснастка опыта), не поведение модели"
            print(f"    разведка ради основания: {_act[2]} юнитом {_act[1]}", flush=True)
            return _act
        _SOURCE[0] = ("РАЗВЕДКА (оснастка опыта «разведка против без разведки»), не поведение модели"
                      if action is not None else
                      "РАЗВЕДКА (оснастка опыта): нераскрытых клеток рядом нет — ход отдан драйверу")
        if action is not None:
            print(f"    разведка (оснастка): {action[2]} юнитом {action[1]}", flush=True)
            return action
    k = int(os.environ.get("V011_DEMO_MOVE", "0") or 0)
    if k > 0:
        _SOURCE[0] = "САМОПРОВЕРКА ЗАПИСИ, не поведение модели"
        units = ((info or {}).get("available_actions") or {}).get("unit") or {}
        if not units:
            return None
        _DEMO["n"] += 1
        if _DEMO["n"] % k:
            return None
        actor_id = sorted(units)[0]
        names = units.get(actor_id) or {}
        want = _DEMO["dirs"][(_DEMO["n"] // k) % len(_DEMO["dirs"])]
        for cand in (want, *sorted(names)):
            if cand in names and names[cand]:
                return ("unit", actor_id, cand)
        return None
    from env.entity_extractor import GameStateExtractor  # noqa: PLC0415
    from env.spec_drive import Decider  # noqa: PLC0415

    turn = (info or {}).get("turn")
    if _DRIVER is None:
        _DRIVER = Decider(GameStateExtractor(my_player_id=int(own_id or 0)),
                          own_id=int(own_id or 0))
    if _LAST_TURN is not None and turn != _LAST_TURN:
        _DRIVER.new_turn()
        _FOUNDING_SHOWN.clear()
    _LAST_TURN = turn
    _record_reveals(obs, (info or {}).get("turn"), V.RUN_TAG)
    action = _DRIVER.decide(obs, info, turn, prev_obs=_PREV_OBS)
    _PREV_OBS = obs
    if action is None and _scout_on and _scout_how == "idle-only" \
            and turn not in _SCOUT_DONE_TURNS:
        _act = _scout_action(obs, info)
        if _act is not None:
            _SCOUT_DONE_TURNS.add(turn)
            _SOURCE[0] = "РАЗВЕДКА ПРИ ПРОСТОЕ (оснастка опыта), не поведение модели"
            print(f"    разведка при простое: {_act[2]} юнитом {_act[1]}", flush=True)
            action = _act
    _SOURCE[0] = ("драйвер: ядро выбрало из измерения" if action is not None
                  else "драйвер: ядро оставило систему на месте")
    for f in ((_DRIVER.log[-1].get("основание") if _DRIVER.log else None) or []):
        key = (f.get("unit"), f.get("прирост"), f.get("причина"))
        if key in _FOUNDING_SHOWN:
            continue
        _FOUNDING_SHOWN.add(key)
        if f.get("прирост") is not None:
            print(f"    основание {f['unit']}: DoF {f.get('doF_поселенца')} → "
                  f"{f.get('doF_города')} = прирост {f['прирост']:+.4f} ({f['причина']})",
                  flush=True)
        else:
            print(f"    основание {f['unit']}: прироста нет — {f['причина']}", flush=True)
    return action


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Живой прогон v0.11 + запись видео")
    ap.add_argument("--port", type=int, default=int(os.environ.get("V011_PORT", "6001")))
    ap.add_argument("--seed", type=int, default=int(os.environ.get("V011_SEED", "9200")))
    ap.add_argument("--turns", type=int, default=int(os.environ.get("V011_TURNS", "80")))
    ap.add_argument("--fps", type=int, default=int(os.environ.get("V011_FPS", "6")))
    ap.add_argument("--no-fog", action="store_true", help="снимать наблюдателем (вся карта)")
    return ap.parse_args()


def live(port: int, seed: int, turns: int, fps: int, fog: bool) -> dict[str, Any]:
    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402
    from civrealm.freeciv.utils.freeciv_logging import log_dir  # noqa: E402

    fc_args["client_port"] = port
    # Сцена: число ИИ-игроков. Скрытые соперники — это `aifill` 8, а не 4 по умолчанию.
    fc_args["aifill"] = int(os.environ.get("V011_AIFILL", "4") or 4)
    # Терпение мира — условие измерения, одинаковое для всех плеч (не коэффициент модели).
    fc_args["server_timeout"] = int(os.environ.get("V011_SERVER_TIMEOUT", "0") or 0) or \
        fc_args.get("server_timeout", 30)
    fc_args["debug.take_screenshot"] = True      # кадры снимает МИР, мы их только собираем
    fc_args["debug.headless"] = True
    fc_args["debug.global_view_screenshot"] = not fog

    shots_root = Path(log_dir) / "screenshots"
    before = set(shots_root.rglob("*.png")) if shots_root.exists() else set()
    trace_path = ROOT / "knowledge" / f"live_trace_{seed}_port{port}{'_' + V.RUN_TAG if V.RUN_TAG else ''}.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace = trace_path.open("w", encoding="utf-8")

    env = gymnasium.make("civrealm/FreecivBase-v0")
    V.install_signal_handlers()
    obs, info = env.reset(client_port=port, seed=seed)
    V._ACTIVE["env"] = env
    V.start_ui_hiding(env)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0
    os.environ["V011_OWN_ID"] = str(own_id)  # оснастка берёт id отсюда, а не угадывает
    extractor = GameStateExtractor(my_player_id=own_id)
    guard = V.install_step_timeout(float(os.environ.get("V011_STEP_TIMEOUT", "60")))
    states: dict[str, tuple[list[str], list[str]]] = {}
    rows: list[dict[str, Any]] = []
    prev_obs = obs
    played = decisions = 0
    outcome = "партия_окончена"

    def capture(o: dict, turn: Any, index: float, counts: dict) -> None:
        for p in V.frames_since(before | set(states), shots_root):
            if p.name in states:
                continue
            left, right = V.state_lines(o or {}, turn, own_id,
                                        dof_lookup=lambda eid: counts.get(eid), index=index)
            states[p.name] = (left, right)

    def marks_like() -> Any:
        """Метки источников коллапса: у извлекателя они внутри трекера наблюдения нападения."""
        tr = getattr(extractor, "attack_tracker", None)
        return getattr(tr, "marks", tr)

    try:
        for _ in range(turns):
            # Ход может содержать несколько решений: спрашиваем `decide`, затем закрываем ход.
            # Без решающего слоя `decide` сразу отдаёт `None`, и прогон остаётся пассивным.
            for _ in range(V.MAX_DECISIONS_PER_TURN):
                action = decide(obs, info, own_id)
                if action is None:
                    break
                print(f"  [решение] {action} ({_SOURCE[0]})", flush=True)
                print(f"    состав ДО действия: "
                      f"{(getattr(_DRIVER, 'last_plan', None) or {}).get('состав')}", flush=True)
                decisions += 1
                with guard():
                    obs, _r, terminated, truncated, info = env.step(action)
                if not obs or terminated or truncated:
                    break
            if _DRIVER is not None and _DRIVER.log:
                e = _DRIVER.log[-1]
                print(f"  [драйвер] ход {e.get('ход')}: состав {e.get('состав')}, "
                      f"кандидатов {e.get('кандидатов')}, "
                      f"выбор {e.get('выбор')}, барьеры {e.get('барьеры')}", flush=True)
            with guard():
                obs, _r, terminated, truncated, info = env.step(None)
            played += 1
            if not obs:
                outcome = "обрыв"                     # мир отдал {} при серверной проблеме
                break
            turn = (info or {}).get("turn")
            m = SO.measure_step(obs, info, turn, extractor, prev_obs=prev_obs, my_player_id=own_id)
            counts = m["counts"]
            try:
                risk, _detail, why = SK.risk_with_reason(obs, marks_like(), turn, own_id, counts)
            except Exception as exc:  # noqa: BLE001
                risk, why = 0.0, f"цена риска не посчитана: {type(exc).__name__}: {str(exc)[:80]}"
            try:
                # Форма возврата: (величина, число строк канала, причина) — строки только этого прогона.
                loss, n_rows, loss_why = extractor.switch_loss_shields()
            except Exception as exc:  # noqa: BLE001
                loss, n_rows = 0.0, 0
                loss_why = f"цена смены не измерена: {type(exc).__name__}: {str(exc)[:80]}"
            marks = getattr(extractor, "marked_collapse_sources", None) or {}
            def _br(measured, counts=None, v_max=None):
                """Разбивка индекса по сущностям ТЕМ ЖЕ счётом ядра.

                Берутся ровно поля измерения порта (`brain/spec/measurement.py:EntityMeasurement`):
                `contribution` (вклад = ln(max(DoF, ε))), `psi` по каналам, `binding_lens` (низшая
                измеренная линза — узкое место), `dof_known`, `floored`. Для города добавляются оба
                объявленных счёта: `V_сейчас` (идёт в индекс) и `V_максимум` (весь каталог), а также
                их разность — объявленная дельта открытия. Второй формулы нет.
                Сортировка — по вкладу вверх: сверху те, кто тянет индекс вниз.
                """
                pairs = list(measured.items()) if isinstance(measured, dict) else list(enumerate(measured or []))
                out = []
                for eid, ent in pairs:
                    psi = getattr(ent, "psi", None) or {}
                    out.append({
                        "id": str(eid),
                        "вид": str(eid).split("_")[0],
                        "dof": round(float(getattr(ent, "current_dof", 0.0) or 0.0), 6),
                        "вклад": round(float(getattr(ent, "contribution", 0.0) or 0.0), 4),
                        "узкое_место": getattr(ent, "binding_lens", None),
                        "знаем": bool(getattr(ent, "dof_known", True)),
                        "пол": bool(getattr(ent, "floored", False)),
                        "psi": {str(k): (round(float(v), 6) if isinstance(v, (int, float)) else v)
                                for k, v in psi.items()},
                    })
                out.sort(key=lambda r: r["вклад"])
                for r in out:
                    if counts is not None and r["id"] in counts:
                        r["V_сейчас"] = round(float(counts[r["id"]]), 1)
                    if v_max and r["id"] in v_max:
                        r["V_максимум"] = round(float(v_max[r["id"]]), 1)
                        if "V_сейчас" in r:
                            r["дельта_открытия"] = round(r["V_максимум"] - r["V_сейчас"], 1)
                return out

            row = {"ход": turn, "индекс": round(float(m["index"]), 4),
                   "сущностей": len(m["measured"]),
                   # §4.2/§13.79: набор расчёта и индекс ЯДРА — рядом с нашим, отдельными числами.
                   # Пустой набор обязан называть своё состояние (`причина_набора`), иначе 0.0
                   # читается как «всё хорошо».
                   "в_расчёте": m.get("в_расчёте"),
                   "индекс_ядра": m.get("индекс_ядра"),
                   "причина_набора": m.get("причина_набора"),
                   # §13.82: вердикт достижимости по сущности — им разводятся «выпала вердиктом»
                   # и «выпала из-за уничтожения» (§13.81 по одной трассе их не различал).
                   "вердикты": m.get("вердикты"),
                   "разбивка": _br(m["measured"], counts, m.get("v_max")),
                   "эффекты_производства": m.get("production_effects") or {},
                   "city_output": m.get("city_output") or {},
                   "медиана_боевой": m.get("median_combat"),
                   "V_всего": round(sum(counts.values()), 1),
                   # Мера парного опыта (в) — СЧЁТ, ПУБЛИКУЕМЫЙ ИГРОЙ (`player[].score`): плечи
                   # различаются правителем, и §3.4.4 запрещает сравнивать их наши числа.
                   "счёт_мира": _score_of_world(obs, own_id),
                   "нападение": getattr(extractor, "last_attack_event", None),
                   # Кандидаты «возможного источника коллапса» (§13.64): ОТДЕЛЬНЫЙ канал.
                   # Подтверждённая метка (`is_collapse_source`) — выше, в `нападение`; здесь —
                   # подозрение с названной причиной, включая посторонних на нашей земле.
                   "кандидаты_коллапса": getattr(extractor, "last_collapse_candidates", None),
                   "меток": len(marks),
                   "строк_смены": n_rows,
                   "цена_смены": loss, "почему_смены": loss_why,
                   "риск": round(float(risk), 4), "почему_риска": why}
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            capture(obs, turn, m["index"], counts)
            if played % 5 == 0 or row["нападение"] or risk > 0:
                _f = lambda v: f"{v:g}" if isinstance(v, (int, float)) else "не измерено"  # noqa: E731
                print(f"  ход {turn}: индекс {row['индекс']:+.3f}, сущностей {row['сущностей']}, "
                      f"V {row['V_всего']:.0f}, нападение {row['нападение']}, меток {row['меток']}, "
                      f"риск {_f(row['риск'])}, смена {_f(row['цена_смены'])}", flush=True)
            prev_obs = obs
            if terminated or truncated:
                outcome = "партия_окончена_миром"
                break
    except V.StepTimeout:
        outcome = "обрыв_шага"
        print("  [клин] шаг не вернулся — партия прервана", flush=True)
    finally:
        trace.close()
        V.cleanup_env(env)
        V._ACTIVE["env"] = None

    frames = V.frames_since(before, shots_root)
    frames = V.draw_state(frames, states, ROOT / "knowledge" / "frames_text" / f"port{port}")
    out = ROOT / "knowledge" / V.video_name(seed, port, ext="mp4")
    ok = V.to_video(frames, out, fps)

    attacks = [r for r in rows if isinstance(r["нападение"], dict) and r["нападение"].get("attacked")]
    risks = [r["риск"] for r in rows]
    summary = {
        "сид": seed, "порт": port, "итог": outcome, "ходов": played, "решений": decisions,
        "кадров": len(frames), "кадров_с_состоянием": len(states),
        "видео": str(out) if ok else None,
        "трасса": str(trace_path),
        "драйвер": [{"ход": e.get("ход"), "индекс": e.get("индекс"), "состав": e.get("состав"),
                     "кандидатов": e.get("кандидатов"), "выбор": e.get("выбор"),
                     "барьеры": e.get("барьеры")} for e in getattr(_DRIVER, "log", [])],
        "нападений_наблюдено": len(attacks),
        "меток_максимум": max((r["меток"] for r in rows), default=0),
        "риск_максимум": round(max(risks), 4) if risks else None,
        "цена_смены": max((r["цена_смены"] or 0.0 for r in rows), default=0.0),
        "индекс_от": rows[0]["индекс"] if rows else None,
        "индекс_до": rows[-1]["индекс"] if rows else None,
        "туман": bool(fog),
    }
    return summary


def main() -> int:
    a = _args()
    print(f"[прогон] туман: {'наш вид агента' if (V.FOG and not a.no_fog) else 'наблюдатель'}; "
          f"окно {V.WINDOW}; метка {V.RUN_TAG or '—'}", flush=True)
    r = live(a.port, a.seed, a.turns, a.fps, fog=(V.FOG and not a.no_fog))
    print("\n===== итог =====")
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
