"""Подключить оценку клеток города перенесённым числом (#13.292).

Ставится замена `_tile_score_of`, когда его числа пусты («строк 0» — измерено в 13.290):
клетки города оцениваются перенесённым `city_tile_value` по выходам из правил мира, а
«снять плохую → занять лучшую» даёт ход только тогда, когда свободная клетка ЛУЧШЕ снимаемой.

Идемпотентно.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

# 1) запомнить наблюдение рядом с контекстом
OLD_CTX = """    global _LAST_CTX
    _LAST_CTX = ctx"""
NEW_CTX = """    global _LAST_CTX, _LAST_OBS
    _LAST_CTX = ctx
    # §13.292: наблюдение нужно, чтобы оценить клетки города правилами мира, когда свои
    # числа пусты. Держим его рядом с контекстом — там же, где живёт всё остальное.
    _LAST_OBS = obs"""

# 2) новая глобальная переменная
OLD_DECL = "_LAST_CTX = None"
NEW_DECL = "_LAST_CTX = None\n#: Наблюдение текущего решения — для оценки клеток города по правилам мира (§13.292).\n_LAST_OBS = None"

HELPER = '''def _city_tile_gains_from_rules(city_id, cands) -> dict:
    """Выигрыш постановки/снятия жителя по ПРАВИЛАМ мира — когда своих чисел нет (§13.292).

    Числа: выходы клетки из правил (`tile_outputs_from_rules`) и ценность перенесённым
    `city_tile_value` (`infracache.c:293`). Порядок «снять плохую → занять лучшую» — его:
    у клиента `city_work` недействителен без свободного горожанина
    (`city/city_actions.py:150`), поэтому снятие оправдано только лучшей свободной клеткой.

    Возвращает `{имя действия: выигрыш}`. Пустой словарь, если данных нет: молчание обязано
    быть отличимо от нуля.
    """
    obs = _LAST_OBS
    if not isinstance(obs, dict):
        return {}
    try:
        from brain.ai_default.city_tiles import (
            parse_city_tile_action, tile_value_from_rules, unwork_gain, work_gain,
            workable_offsets,
        )
        from env.terrain_work import tile_terrain_extras
    except Exception:  # noqa: BLE001
        return {}

    rec = (as_dict(obs.get("city")) or {}).get(str(city_id))
    if not isinstance(rec, dict) or rec.get("x") is None or rec.get("y") is None:
        return {}
    cx, cy = int(rec["x"]), int(rec["y"])
    map_obs = as_dict(obs.get("map")) or {}

    def _value(dx: int, dy: int):
        try:
            terrain, extras = tile_terrain_extras(map_obs, cx + dx, cy + dy)
        except Exception:  # noqa: BLE001
            return None
        return tile_value_from_rules(terrain, extras)

    # Какие клетки заняты: говорит сам стенд — он предлагает снятие именно с занятых.
    worked, free_offered = {}, {}
    for c in cands or ():
        if str(c.get("ctrl_type")) != "city" or str(c.get("actor_id")) != str(city_id):
            continue
        name = str(c.get("action_name") or "")
        parsed = parse_city_tile_action(name)
        if parsed is None:
            continue
        _idx, dx, dy = parsed
        if name.startswith("city_unwork_"):
            worked[name] = _value(dx, dy)
        elif name.startswith("city_work_"):
            free_offered[name] = _value(dx, dy)

    # Свободные клетки: городской радиус минус занятые. Радиус — правило движка
    # (`common/map.c:628`, `common/map.h:397`).
    taken = {(parse_city_tile_action(n)[1], parse_city_tile_action(n)[2]) for n in worked}
    free_values = [v for (dx, dy) in workable_offsets(rec.get("city_radius_sq"))
                   if (dx, dy) not in taken and (v := _value(dx, dy)) is not None]
    free_values += [v for v in free_offered.values() if v is not None]

    gains = {}
    for name, value in worked.items():
        gains[name] = unwork_gain(value, free_values)
    best_worked = max([v for v in worked.values() if v is not None], default=None)
    for name, value in free_offered.items():
        gains[name] = work_gain(value, best_worked)
    if os.environ.get("DOF_TILE_DEBUG") == "1" and gains:
        print(f"  [клетка-правила] город {city_id}: занято {len(worked)}, свободно "
              f"{len(free_values)}; выигрыши "
              f"{ {k: round(v, 1) for k, v in gains.items()} }", flush=True)
    return gains


'''

OLD_LOOP = """                    for _cand in descore:
                        _gain = _tile_score_of(_LAST_CTX, _cand.get("ctrl_type"),
                                               _cand.get("action_name"),
                                               _cand.get("actor_id"))"""

NEW_LOOP = """                    _rule_gains: dict = {}
                    _tile_cities = sorted({
                        str(c.get("actor_id")) for c in descore
                        if str(c.get("ctrl_type")) == "city"
                        and str(c.get("action_name") or "").startswith(
                            ("city_work_", "city_unwork_"))})
                    for _cid in _tile_cities:
                        _rule_gains.update(_city_tile_gains_from_rules(_cid, descore))
                    for _cand in descore:
                        _gain = _tile_score_of(_LAST_CTX, _cand.get("ctrl_type"),
                                               _cand.get("action_name"),
                                               _cand.get("actor_id"))
                        if _gain is None or _gain <= 0.0:
                            # §13.292: своих чисел на клетку города нет вовсе (измерено:
                            # «строк 0»). Тогда ценность клетки берётся перенесённым числом
                            # по правилам мира, а выигрыш — по порядку «снять плохую →
                            # занять лучшую», тоже его.
                            _rule_gain = _rule_gains.get(str(_cand.get("action_name") or ""))
                            if _rule_gain:
                                _gain = _rule_gain"""

text = PATH.read_text(encoding="utf-8")
n = 0
if "_LAST_OBS = None" in text:
    print("глобальная переменная уже есть")
else:
    assert text.count(OLD_DECL) >= 1, "якорь объявления не найден"
    text = text.replace(OLD_DECL, NEW_DECL, 1)
    n += 1

if "    _LAST_OBS = obs" in text:
    print("запоминание наблюдения уже есть")
else:
    assert text.count(OLD_CTX) == 1, "якорь контекста не однозначен"
    text = text.replace(OLD_CTX, NEW_CTX)
    n += 1

if "def _city_tile_gains_from_rules(" in text:
    print("помощник уже есть")
else:
    anchor = "def _tile_score_of(ctx, ctrl_type, action_name, actor_id=None):"
    assert text.count(anchor) == 1, "якорь вставки не однозначен"
    text = text.replace(anchor, HELPER + anchor)
    n += 1

if "_rule_gain = _rule_gains.get(" in text:
    print("подстановка уже есть")
else:
    assert text.count(OLD_LOOP) == 1, "якорь цикла не однозначен"
    text = text.replace(OLD_LOOP, NEW_LOOP)
    n += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {n}")
ast.parse(text)
print("синтаксис ок")
