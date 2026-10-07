"""ПОДГОТОВЛЕНО, НЕ ПРИМЕНЕНО. Правка §13.66: ноль в цене риска обязан называть своё состояние.

Владелец (2026-10-07): «в игре "угроз нет" может быть только если наш игрок один на сервере».

Что не так в `env/spec_risk.py::risk_with_reason`: при пустом множестве наблюдённых угроз и
отсутствии живых меток текст причины говорит «угроз нет», хотя при живых соперниках честное
состояние иное — «нападений не наблюдалось; соперники есть, но угрозы не наблюдены». Правило
проекта (I45, §10.111–10.115): ноль обязан называть, КАКОЙ он: «опасности нет» / «мы перестали
смотреть» / «не достают».

Применять ПОСЛЕ закрытия идущего опыта: файл загружается плечами, правка на ходу сделала бы их
несравнимыми. Запуск: .venv/bin/python scripts/_apply_risk_zero_reason.py
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "env" / "spec_risk.py"

OLD = '''    if not found:
        if active:
            return 0.0, {}, (f"источник коллапса известен ({len(active)}), но в текущем наблюдении "
                             f"не виден: по устаревшим координатам не считаем — «видели бы» там, "
                             f"где его давно нет")
        return 0.0, {}, ("нападения ещё не наблюдалось — угроз нет; цена риска нулевая не потому, "
                         "что опасности нет, а потому что нападения не было")
'''

NEW = '''    if not found:
        if active:
            return 0.0, {}, (f"источник коллапса известен ({len(active)}), но в текущем наблюдении "
                             f"не виден: по устаревшим координатам не считаем — «видели бы» там, "
                             f"где его давно нет")
        powers = foreign_powers(obs, my_player_id)
        if powers == 0:
            return 0.0, {}, ("мы на карте одни: чужих игроков нет — угроз нет по существу, "
                             "а не потому, что их не видно")
        if powers is None:
            return 0.0, {}, ("нападений ещё не наблюдалось; о соперниках данных нет — состояние "
                             "не измерено, «угроз нет» НЕ утверждается")
        return 0.0, {}, (f"нападений ещё не наблюдалось, но на карте {powers} чужих игроков: "
                         f"угрозы есть, они просто не наблюдены (мы их не видели) — цена риска "
                         f"нулевая именно поэтому")
'''

HELPER = '''

def foreign_powers(obs: Mapping[str, Any], my_player_id: Any = 0) -> Optional[int]:
    """Сколько ЧУЖИХ игроков насчитывает наблюдение: `None` — данных нет.

    «Угроз нет» — утверждение о мире, и оно допустимо лишь тогда, когда чужих игроков нет
    вовсе (владелец: в игре это возможно только если наш игрок один на сервере). Отсутствие
    наблюдённых нападений при живых соперниках — это «не наблюдено», а не «нет угроз».

    Чтение ключей терпимое: мир отдаёт секции то числами, то строками (правило наблюдения).
    """
    section = (obs or {}).get("player")
    if not isinstance(section, Mapping):
        return None
    try:
        me = int(my_player_id)
    except (TypeError, ValueError):
        me = 0
    powers = 0
    for key, rec in section.items():
        try:
            pid = int((rec or {}).get("id", key)) if isinstance(rec, Mapping) else int(key)
        except (TypeError, ValueError):
            continue
        if pid != me:
            powers += 1
    return powers

'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "def foreign_powers(" in text:
        print("уже применено — ничего не делаю")
        return
    n_old = text.count(OLD)
    if n_old != 1:
        print(f"ОТКАЗ: вхождение старой ветки найдено {n_old} раз, ожидалось ровно одно")
        raise SystemExit(1)
    anchor = "def risk_with_reason("
    if text.count(anchor) != 1:
        print("ОТКАЗ: точка вставки неоднозначна")
        raise SystemExit(1)

    out = text.replace(OLD, NEW)
    out = out.replace(anchor, HELPER.lstrip("\n") + "\n" + anchor, 1)
    ast.parse(out)                      # синтаксис проверяется ДО записи
    TARGET.write_text(out, encoding="utf-8")

    after = TARGET.read_text(encoding="utf-8")
    print("применено:", "def foreign_powers(" in after)
    print("старая формулировка осталась:", "угроз нет; цена риска нулевая не потому" in after)
    print("новая ветка есть:", "угрозы есть, они просто не наблюдены" in after)


if __name__ == "__main__":
    main()
