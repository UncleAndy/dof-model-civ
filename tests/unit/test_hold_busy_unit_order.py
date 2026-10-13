"""Занятому юниту — не выдавать ДРУГОЙ приказ (§13.281).

Измерено (`/tmp/dof_growth.log`, `--dump-state 20`): город не растёт, потому что улучшение
клетки не завершается — юнит получает каждый ход другой приказ:

```
состояние 8:  unit/114 mine
состояние 9:  unit/114 build_road
состояние 10: unit/114 mine
состояние 11: unit/114 build_road
```

Каждый новый приказ отменяет предыдущий, клетка остаётся базовой, `prod_food` = 2, излишек
еды 0 (`2 − 2`), город навсегда на размере 1 — 1 город и население 1 против 23 и 182 у
встроенного ИИ.

Мир САМ сообщает занятие юнита: `unit_ctrl.units[id]['activity']`, значения —
`ACTIVITY_IDLE = 0`, `ACTIVITY_MINE = 2`, `ACTIVITY_GEN_ROAD = 13`, `ACTIVITY_PLANT = 15`
(`civrealm/.../version/v14.py:50`). Измерено на живом прогоне: значения приходят (0, 13, 15),
то есть юниты действительно заняты.

Порядок приоритетов сохраняется: основание города — решение игры, оно ВЫШЕ работы клетки
(§13.271/13.276), поэтому занятому поселенцу основание разрешено, а смена рода работы — нет.

Первое предположение («правило применяем только если предложен `keep_activity`») замер
ОПРОВЕРГ: у занятых юнитов `keep_activity` в предложении нет, поэтому правило молчало и
чередование продолжалось. Отсюда два условия вместо одного: другой приказ занятому юниту
не выдаём; но если после этого у стороны не осталось НИ ОДНОГО хода — возвращаем исходное,
потому что сторона без хода хуже смены приказа.
"""
from __future__ import annotations

import importlib.util as _util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "baselines" / "run_real_tournament.py"

IDLE = 0            # ACTIVITY_IDLE
BUSY_MINE = 2       # ACTIVITY_MINE
BUSY_ROAD = 13      # ACTIVITY_GEN_ROAD — наблюдалось на живом прогоне
BUSY_PLANT = 15     # ACTIVITY_PLANT — наблюдалось на живом прогоне


def _runner():
    spec = _util.spec_from_file_location("rt_hold", RUNNER)
    mod = _util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _c(ctrl: str, actor: str, name: str) -> dict:
    return {"ctrl_type": ctrl, "actor_id": actor, "action_name": name}


def test_busy_unit_keeps_working_instead_of_switching():
    """Смена рода работы у занятого юнита — то, из-за чего улучшение не завершалось."""
    rt = _runner()
    cands = [_c("unit", "114", "build_road"),
             _c("unit", "114", "mine"),
             _c("unit", "114", "keep_activity")]
    out = rt._hold_busy_unit_orders(cands, activities={"114": BUSY_MINE})
    assert [c["action_name"] for c in out] == ["keep_activity"], out


def test_busy_unit_may_still_found_a_city():
    """Основание — решение игры, оно выше работы: занятый поселенец обязан мочь основать."""
    rt = _runner()
    cands = [_c("unit", "114", "build_road"),
             _c("unit", "114", "build_city"),
             _c("unit", "114", "keep_activity")]
    out = rt._hold_busy_unit_orders(cands, activities={"114": BUSY_MINE})
    names = sorted(c["action_name"] for c in out)
    assert names == ["build_city", "keep_activity"], names


def test_busy_road_builder_is_not_switched_to_mine():
    """Измеренный случай: занятие 13 (дорога) — шахту поверх не выдаём."""
    rt = _runner()
    cands = [_c("unit", "115", "mine"), _c("city", "121", "produce_Warriors")]
    out = rt._hold_busy_unit_orders(cands, activities={"115": BUSY_ROAD})
    assert [c["action_name"] for c in out] == ["produce_Warriors"], out


def test_busy_planter_is_not_switched():
    """Измеренный случай: занятие 15 (посадка)."""
    rt = _runner()
    cands = [_c("unit", "116", "build_road"), _c("unit", "117", "goto_0"),
             _c("city", "121", "produce_Settlers")]
    out = rt._hold_busy_unit_orders(cands, activities={"116": BUSY_PLANT, "117": IDLE})
    names = [c["action_name"] for c in out]
    assert "build_road" not in names, out
    assert "goto_0" in names, out
    assert "produce_Settlers" in names, out


def test_hold_never_leaves_the_side_without_a_move():
    """Если после удержания не осталось НИ ОДНОГО хода — возвращаем исходное."""
    rt = _runner()
    cands = [_c("unit", "114", "mine")]
    out = rt._hold_busy_unit_orders(cands, activities={"114": BUSY_MINE})
    assert [c["action_name"] for c in out] == ["mine"], out


def test_idle_unit_is_untouched():
    """Правило не смеет мешать свободному юниту: иначе агент перестанет ходить."""
    rt = _runner()
    cands = [_c("unit", "114", "mine"), _c("unit", "114", "goto_0")]
    out = rt._hold_busy_unit_orders(cands, activities={"114": IDLE})
    assert [c["action_name"] for c in out] == ["mine", "goto_0"], out


def test_unknown_activity_means_no_hold():
    """Юнита нет в записях мира — правило молчит, а не режет вслепую."""
    rt = _runner()
    cands = [_c("unit", "999", "mine")]
    out = rt._hold_busy_unit_orders(cands, activities={})
    assert [c["action_name"] for c in out] == ["mine"], out


def test_city_candidates_are_never_touched():
    """Правило про юнитов: города оно не трогает."""
    rt = _runner()
    cands = [_c("city", "121", "produce_Settlers")]
    out = rt._hold_busy_unit_orders(cands, activities={"114": BUSY_MINE})
    assert [c["action_name"] for c in out] == ["produce_Settlers"], out
