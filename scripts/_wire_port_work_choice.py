"""Подключить перенесённый выбор работы к ОБЩЕМУ пути (§13.288).

Почему на общий путь. Решение рабочего у нас стоит за гейтом `if not ARGS.forecast:
return False, None`, то есть при `--no-dof` не вызывается вовсе (13.286). Четвёртый случай
одного дефекта: правило живёт там, где ничего не вызывается.

Что делает правка: для юнитов, которым стенд предлагает работы клетки, выбирает работу
ПЕРЕНОСЁННЫМ правилом встроенного ИИ (`choose_tile_work` по `autoworkers.c:439`) и оставляет
среди кандидатов только выбранную. Данные — из мира:

* террейн клетки — `env.terrain_work.tile_terrain_extras` (правила мира);
* текущие выходы клетки — `env.terrain_output.server_tile_outputs` (серверные значения его же
  городских пакетов);
* приросты и сроки работ — `env.terrain_work_effects` / `env.terrain_work_times`.

Предохранители (без них правка опаснее, чем её отсутствие):

1. Нет данных о клетке — правило МОЛЧИТ, кандидаты не трогаются.
2. Выбранной работы нет среди предложенных — не трогаем.
3. Если после отбора у стороны не осталось хода — возвращаем исходное.
4. Любой сбой — кандидаты не трогаются, под следом печатается причина.

Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

HELPER = '''def _port_work_choice_for(actor, candidates, obs, dof_state):
    """Работа, которую выбрал бы встроенный ИИ на клетке этого юнита (§13.288).

    Возвращает имя работы или None, если данных не хватает (тогда правило молчит).
    """
    try:
        from brain.ai_default.worker_choice import choose_tile_work, work_options_from_rules
        from env.terrain_output import server_tile_outputs
        from env.terrain_work import tile_terrain_extras
    except Exception:  # noqa: BLE001
        return None

    positions = getattr(dof_state, "positions", None) or {}
    pos = positions.get(str(actor)) or positions.get(f"unit_{actor}")
    if not pos:
        return None
    try:
        x, y = int(pos[0]), int(pos[1])
    except (TypeError, ValueError, IndexError):
        return None

    map_obs = obs.get("map") if isinstance(obs, dict) else None
    if not isinstance(map_obs, dict):
        return None
    try:
        terrain, _extras = tile_terrain_extras(map_obs, x, y)
    except Exception:  # noqa: BLE001
        return None
    if not terrain:
        return None

    city_actions = {}
    try:
        avail = (obs.get("avail") or {}) if isinstance(obs, dict) else {}
        city_actions = avail.get("city") or {}
    except Exception:  # noqa: BLE001
        city_actions = {}
    outputs_by_city = {}
    try:
        outputs_by_city = server_tile_outputs(city_actions, x, y)
    except Exception:  # noqa: BLE001
        outputs_by_city = {}
    if not outputs_by_city:
        # Выход клетки вне городов нам не сообщается: без него ценность клетки не собрать,
        # а подставлять ноль запрещено (нули `map.output` отозваны).
        return None
    outputs = next(iter(outputs_by_city.values()))

    offered = []
    for c in candidates:
        act = _to_action(c)
        if act and str(act[0]) == "unit" and str(act[1]) == str(actor):
            offered.append(str(act[2]))
    options = work_options_from_rules(str(terrain), tuple(outputs), offered)
    if not options:
        return None
    try:
        choice = choose_tile_work([((x, y), tuple(outputs), options)])
    except Exception:  # noqa: BLE001
        return None
    return choice.activity or None


def _prefer_port_work_choice(cands: list, obs: dict, dof_state) -> list:
    """Оставить выбранную ИМ работу среди предложенных работ КАЖДОГО юнита (§13.288).

    Измерено за этот заход: работу клетки выбирал счёт совпадений со списком предпочтений
    (`_preference_score`), поэтому шли шахта и дорога, а город стоял на размере 1 при
    излишке еды 0 (13.280). Теперь работу выбирает ЕГО правило.
    """
    by_actor: dict = {}
    for c in cands:
        act = _to_action(c)
        if not act or str(act[0]) != "unit":
            continue
        name = str(act[2])
        if name in ("mine", "irrigation"):
            by_actor.setdefault(str(act[1]), []).append(name)
    if not by_actor:
        return cands

    keep: dict = {}
    for actor in by_actor:
        chosen = _port_work_choice_for(actor, cands, obs, dof_state)
        if chosen:
            keep[actor] = chosen
    if not keep:
        return cands

    out = []
    for c in cands:
        act = _to_action(c)
        if not act:
            out.append(c)
            continue
        ctrl, actor, name = str(act[0]), str(act[1]), str(act[2])
        chosen = keep.get(actor)
        if ctrl == "unit" and chosen and name in ("mine", "irrigation") and name != chosen:
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"  [работа-перенос] unit/{actor}: {name} отложено — его правило "
                      f"выбрало {chosen}", flush=True)
            continue
        out.append(c)
    if not out:
        return cands
    return out


'''

CALL_OLD = '''                    descore = _apply_common_rules(
                        gen.generate_candidates(dof.state, avail), obs, extractor,
                        env_getter, avail)
'''
CALL_NEW = '''                    descore = _apply_common_rules(
                        gen.generate_candidates(dof.state, avail), obs, extractor,
                        env_getter, avail)
                    # §13.288: работу клетки выбирает ПЕРЕНОСЁННОЕ правило встроенного ИИ,
                    # а не счёт совпадений со списком. На ОБЩЕМ пути: у решения рабочего
                    # был свой гейт (`if not ARGS.forecast`), и при --no-dof оно не
                    # вызывалось вовсе — четвёртый случай одного дефекта (13.286).
                    descore = _prefer_port_work_choice(descore, obs, dof.state)
'''

text = PATH.read_text(encoding="utf-8")
changed = 0

if "def _prefer_port_work_choice(" in text:
    print("функции уже есть")
else:
    anchor = "def _is_action_wedged(ctrl: str, name: str, position) -> bool:"
    assert text.count(anchor) == 1, "якорь вставки не однозначен"
    text = text.replace(anchor, HELPER + anchor)
    changed += 1

if "_prefer_port_work_choice(descore, obs, dof.state)" in text:
    print("вызов уже есть")
else:
    assert text.count(CALL_OLD) == 1, "якорь вызова не однозначен"
    text = text.replace(CALL_OLD, CALL_NEW)
    changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
