"""§13.294: решение о клетке города — обязательная часть хода, а не участник общего конкурса.

Измерено (13.293): короткий список генератора даёт 4–5 кандидатов (топ по приросту DoF), и
`city_work_*` в него не попадает вовсе — при том что мир предлагает 21 клетку радиуса с
НЕПУСТЫМИ параметрами. Поэтому освобождённого горожанина поставить нечем.

Правка: кандидат собирается НАПРЯМУЮ из предложенного миром (мимо короткого списка), и его
выбор делает перенесённая оценка клетки (`city_tile_value` по правилам). Ставится перед
постановкой в городе, потому что рост упирается именно в клетку.

Осторожно с чередованием: измерено (§13.232), что `city_unwork_X` и `city_work_X` одной
клетки, чередуясь каждый ход, давали прирост еды +0 и сброс щитов. Защита от обратного хода
жила только в выключенном пути прогноза — здесь она повторяется для общего пути.

Идемпотентно.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

HELPER = '''def _city_tile_candidate(obs: dict, avail: dict):
    """Какое действие по клетке города отправить — по перенесённой оценке (§13.294).

    Мир предлагает до 21 клетки радиуса с непустыми параметрами (`city_work_*`), но короткий
    список генератора их не берёт: прирост DoF у постановки жителя почти нулевой. У его
    управляющего городом расстановка жителей — обязательная часть хода (`cm.c`), поэтому
    кандидат собирается напрямую из предложенного, а выбирает его перенесённое число.

    Возвращает `(ctrl, actor, action)` или None. None — если данных нет ИЛИ лучший ход был бы
    обратным к нашему же прошлому ходу по этой клетке (чередование измеренно вредит).
    """
    city_actions = as_dict(as_dict(avail).get("city")) or {}
    best = None
    for cid, actions in city_actions.items():
        names = [str(n) for n, params in as_dict(actions).items()
                 if str(n).startswith(("city_work_", "city_unwork_")) and truthy(params)]
        if not names:
            continue
        cands = [{"ctrl_type": "city", "actor_id": cid, "action_name": n} for n in names]
        gains = _city_tile_gains_from_rules(cid, cands, obs=obs)
        if not gains:
            continue
        # Обратный ход к нашему же прошлому действию по той же клетке не отправляем.
        _prev = _LAST_TILE_ACTION.get(str(cid))
        _prev_bench = None
        if _prev:
            _prev_bench = (str(_prev)[len("city_unwork_"):]
                           if str(_prev).startswith("city_unwork_")
                           else str(_prev)[len("city_work_"):])
        for name in sorted(gains, key=lambda n: -gains[n]):
            gain = gains[name]
            if gain <= 0:
                break
            if _prev_bench is not None and name[len("city_unwork_"):] == _prev_bench \\
                    and (name.startswith("city_unwork_") != str(_prev).startswith("city_unwork_")):
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"  [клетка-ход] {name} пропущено: обратный ход к {_prev}", flush=True)
                continue
            if best is None or gain > best[0]:
                best = (gain, str(cid), name)
            break
    if best is None:
        return None
    gain, cid, name = best
    _LAST_TILE_ACTION[cid] = name
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        print(f"  [клетка-ход] город {cid}: {name} (перенесённая оценка +{gain:.1f})", flush=True)
    return ("city", cid, name)


'''

OLD_SIG = "def _city_tile_gains_from_rules(city_id, cands) -> dict:"
NEW_SIG = "def _city_tile_gains_from_rules(city_id, cands, obs=None) -> dict:"

OLD_OBS = """    obs = _LAST_OBS
    if not isinstance(obs, dict):"""
NEW_OBS = """    obs = obs if isinstance(obs, dict) else _LAST_OBS
    if not isinstance(obs, dict):"""

# Вставка перед постановкой в городе: рост упирается в клетку, поэтому её ход идёт первым.
OLD_CALL = """                    _prod = _production_candidate("""
NEW_CALL = """                    # §13.294: ход по клетке города — ПЕРВЫМ. Измерено (13.293): короткий
                    # список генератора не берёт `city_work_*` (нулевой прирост DoF), поэтому
                    # освобождённого горожанина поставить нечем и город стоит на размере 1.
                    _tile_pick = _city_tile_candidate(obs, avail)
                    if _tile_pick is not None:
                        return _tile_pick
                    _prod = _production_candidate("""

text = PATH.read_text(encoding="utf-8")
n = 0

if "def _city_tile_candidate(" in text:
    print("помощник уже есть")
else:
    anchor = "def _city_tile_gains_from_rules("
    assert text.count(anchor) == 1, "якорь вставки не однозначен"
    text = text.replace(anchor, HELPER + anchor)
    n += 1

if NEW_SIG in text:
    print("подпись уже правлена")
else:
    assert text.count(OLD_SIG) == 1, "подпись не однозначна"
    text = text.replace(OLD_SIG, NEW_SIG)
    n += 1

if "obs = obs if isinstance(obs, dict) else _LAST_OBS" in text:
    print("источник наблюдения уже правлен")
else:
    assert text.count(OLD_OBS) == 1, "якорь наблюдения не однозначен"
    text = text.replace(OLD_OBS, NEW_OBS)
    n += 1

if "_tile_pick = _city_tile_candidate(obs, avail)" in text:
    print("вызов уже есть")
else:
    assert text.count(OLD_CALL) == 1, "якорь постановки не однозначен"
    text = text.replace(OLD_CALL, NEW_CALL)
    n += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {n}")
ast.parse(text)
print("синтаксис ок")
