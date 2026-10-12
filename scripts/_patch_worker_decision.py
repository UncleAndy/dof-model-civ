"""Отдельное решение рабочего (§13.259): работа по клетке не соревнуется с городом.

У встроенного ИИ работа и производство города — РАЗНЫЕ решения: его
`settler_evaluate_improvements` (`server/advisors/autoworkers.c`) спрашивает «есть ли клетка,
которую стоит улучшить?», и если ответ > 0, рабочий идёт работать. В нашей общей куче кандидатов
работа проигрывает ходу и постройке по построению (0.03 против 0.47 и 2.08), поэтому выгода,
посчитанная по числам мира, до дела не доходит.

Здесь добавляется отдельный ход рабочего: если у нашего рабочего есть предложенная миром работа с
НЕНУЛЕВОЙ выгодой, она исполняется, а общий отбор её не перебивает.
"""
from __future__ import annotations

import pathlib

LIVE = pathlib.Path("/home/hermes/projects/AI/DOF-MODEL-CIV/brain/forecast/live.py")
RUNNER = pathlib.Path("/home/hermes/projects/AI/DOF-MODEL-CIV/baselines/run_real_tournament.py")

FUNC = '''

def worker_work_choice(obs, info, extractor, my_id):
    """Лучшая работа рабочего с ненулевой выгодой: `('unit', ключ, действие)` или None (§13.259).

    Почему отдельным решением. У встроенного ИИ (`autoworkers.c`) работа по клетке — самостоятельный
    вопрос, а не кандидат в общем списке: его рабочий не соревнуется с производством города. У нас
    общая куча кандидатов, и там работа проигрывала ходу на два порядка (измерено §13.259), хотя
    выгода по числам мира ненулевая. Здесь она берётся так, как её берёт он: есть работа с выгодой
    больше нуля — рабочий её делает.

    Кто может работать — решает ПРЕДЛОЖЕНИЕ мира (`available_actions`), а не наш признак типа
    (§13.177). Выгода — из измеренного пути, который адресует её городу формулой города; ноль
    остаётся нулём и действием не становится.
    """
    from env.terrain_work import WORK_ACTION_EXTRA

    try:
        units = as_dict(obs.get("unit"))
    except Exception:  # noqa: BLE001
        return None
    workers = []
    for ukey, u in units.items():
        if not isinstance(u, dict):
            continue
        if my_id is not None and u.get("owner") is not None \\
                and str(u.get("owner")) != str(my_id):
            continue
        tname = str(u.get("type_rule_name") or u.get("type") or "")
        if "Worker" in tname or "Engineer" in tname:
            workers.append(ukey)
    if not workers:
        return None

    try:
        bridge = extractor.extract(obs, info, 1).state.bridge
    except Exception:  # noqa: BLE001
        return None
    gains = getattr(bridge, "terrain_work_gain_by_unit", {}) or {}
    offered_map = as_dict(as_dict(info.get("available_actions")).get("unit"))

    best: tuple[float, tuple[str, str, str]] | None = None
    for ukey in workers:
        uid = ukey.split("_", 1)[1] if "_" in str(ukey) else str(ukey)
        acts = as_dict(offered_map.get(int(uid)) if str(uid).isdigit() else None) \\
            or as_dict(offered_map.get(str(uid))) or as_dict(offered_map.get(str(ukey)))
        per_unit = gains.get(ukey, {}) or {}
        for action, extra in WORK_ACTION_EXTRA.items():
            if not acts.get(action):
                continue
            value = float(per_unit.get(extra, 0.0) or 0.0)
            if value > 0.0 and (best is None or value > best[0]):
                best = (value, ("unit", str(ukey), str(action)))
    return best[1] if best else None
'''

src = LIVE.read_text(encoding="utf-8")
assert "def worker_work_choice" not in src, "функция уже вставлена"
src = src.rstrip() + FUNC
LIVE.write_text(src, encoding="utf-8")

runner = RUNNER.read_text(encoding="utf-8")
OLD = '''    if not ARGS.forecast:
        return False, None'''
NEW = '''    if not ARGS.forecast:
        return False, None
    # Отдельное решение рабочего (§13.259): как у встроенного ИИ, работа по клетке не соревнуется
    # с ходом и производством города. Признак печатается — иначе «работы не было» и «решение не
    # подключено» неразличимы.
    if getattr(ARGS, "worker_work", True):
        try:
            _ww = _live.worker_work_choice(obs, info, extractor,
                                           getattr(extractor, "my_player_id", None))
        except Exception as _exc:  # noqa: BLE001 - не рушим матч диагностикой
            _ww = None
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"        [рабочий] сбой решения: {type(_exc).__name__}: {_exc}", flush=True)
        if _ww is not None:
            _FORECAST_STATS["worker_work"] = _FORECAST_STATS.get("worker_work", 0) + 1
            try:
                _wtn = int((info or {}).get("turn") or (info or {}).get("turn_played") or -1)
            except (TypeError, ValueError):
                _wtn = -1
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"        [прогноз] отправляю (ход {_wtn}) работа: {_ww[2]} "
                      f"(актёр {_ww[1]})", flush=True)
            return True, _ww'''
assert OLD in runner, "место начала решения не найдено"
runner = runner.replace(OLD, NEW, 1)

# Флаг: отдельный ход рабочего можно выключить (для сверочной ветви замера).
OLD_ARG = '''    parser.add_argument("--no-tile-actions", dest="no_tile_actions",'''
NEW_ARG = '''    parser.add_argument("--no-worker-work", dest="worker_work", action="store_false",
                        default=True,
                        help="выключить отдельное решение рабочего (§13.259) — сверочная ветвь")
    parser.add_argument("--no-tile-actions", dest="no_tile_actions",'''
assert OLD_ARG in runner, "место аргумента --no-tile-actions не найдено"
runner = runner.replace(OLD_ARG, NEW_ARG, 1)
RUNNER.write_text(runner, encoding="utf-8")
print("встроено: worker_work_choice + отдельный ход рабочего + флаг --no-worker-work")
