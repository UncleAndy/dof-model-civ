"""Сторож на рецепт городского управляющего: номера пакетов и числа мира.

Пакет найден §13.237-13.238: `PACKET_WEB_CMA_SET = 257`, `PACKET_WEB_CMA_CLEAR = 258`.
Номера сверены ДВУМЯ источниками (пакет обёртки стенда v14 и `packets.js:75-76` клиента
веба) и разбором `enum packet_type`; способ сверки проверен на известном пакете
(`packet_city_make_specialist = 37`).

Числа внутри — числа МИРА (`set_default_city_manager`, `server/cityturn.c:313-360`), а не
наши: еда 20 при размере 1, 15 при 2..notradesize, 10 выше; щиты 5; торговля и роскошь 0;
золото 2; наука 2; порядок выходов — food, shield, trade, gold, luxury, science. Если
кто-то поменяет их «на глаз», сторож обязан упасть: иначе пороги поедут молча.

Путь живого матча в тестах не исполняется (дорог — стоит партии), поэтому проверка
статическая — как в `test_production_hold_silence.py` и `test_tile_action_hold.py`.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "baselines" / "run_real_tournament.py"

#: Числа мира, которые обязаны быть в требованиях управляющему (`cityturn.c:313-360`).
_WORLD_NUMBERS = ("20", "15", "5", "2", "0")


def _const(tree: ast.AST, name: str) -> object:
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


def _params_segment(tree: ast.AST) -> str:
    src = RUNNER.read_text(encoding="utf-8")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_city_manager_params":
            return ast.get_source_segment(src, node) or ""
    return ""


def test_packet_numbers_are_the_ones_verified_twice():
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    assert _const(tree, "_CMA_SET_PID") == 257, "номер PACKET_WEB_CMA_SET обязан быть 257"
    assert _const(tree, "_CMA_CLEAR_PID") == 258, "номер PACKET_WEB_CMA_CLEAR обязан быть 258"


def test_parameters_use_the_worlds_numbers_and_axis_order():
    seg = _params_segment(ast.parse(RUNNER.read_text(encoding="utf-8")))
    assert seg, "функция `_city_manager_params` не найдена — сторож ослеп"
    for num in _WORLD_NUMBERS:
        assert num in seg, (
            f"число мира {num} пропало из требований управляющему: числа обязаны быть его "
            f"(`set_default_city_manager`), а не придуманными (§13.238)"
        )
    # Порядок осей: сперва минимумы (food, shield, trade, gold, luxury, science),
    # затем коэффициенты тем же порядком.
    # Сравниваем именно КЛЮЧИ словаря: слово «factor» встречается и внутри `food_factor`,
    # из-за чего проверка подстрокой падала ложно (поймано прогоном сторожа).
    assert seg.index('"minimal_surplus"') < seg.index('"factor"'), (
        "порядок полей сменился: `minimal_surplus` идёт до `factor` (cm.h:40-49)"
    )
    assert "happy_factor" in seg, "поле `happy_factor` пропало из запроса управляющему"