#!/usr/bin/env python
"""Правка вендорного CivRealm: не падать на пустом `action_prob`.

Причина (измерена на живом прогоне, /tmp/h300p_ban.log):
    File ".../civrealm/freeciv/units/unit_actions.py", line 923, in is_action_valid
        return action_prob_possible(self.focus.action_prob[map_const.DIR8_STAY][...])
    KeyError: -1

`map_const.DIR8_STAY == -1` (map_const.py:1). Словарь `action_prob` заполняется
ответами сервера `get_pro` по направлению (unit_actions.py:271). Если у юнита не
осталось хода, сервер `get_pro` не присылает, и словарь пуст — это задокументировано
самим апстримом (unit_actions.py:313: «If a unit has no move left, it will not send
get_pro action. Its corresponding action_prob will be {}»). Апстрим же обращается к
`action_prob[DIR8_STAY]` напрямую и падает, убивая весь эпизод.

Смысл правки: отсутствие данных = действие невозможно (ровно то, что апстрим
подразумевает словами, но не проверяет кодом). Логика игры не меняется: меняется
только поведение на неполных данных — с падения на «нельзя».

Запуск: python scripts/patches/apply_action_prob_guard.py [--check]
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "civrealm/src/civrealm/freeciv/units/unit_actions.py"
BACKUP = Path(__file__).resolve().parent / "unit_actions.py.orig"
PATCH = Path(__file__).resolve().parent / "civrealm-action-prob-guard.patch"

HELPER = '''

def action_prob_of(focus_action_prob: dict, dir8: int, action_key: int) -> bool:
    """Возможность действия по вероятностям сервера — БЕЗ падения на пустом словаре.

    Сервер не присылает `get_pro` для юнита без остатка хода, и тогда `action_prob`
    пуст (см. `query_action_probablity`). Апстрим обращается к
    `action_prob[DIR8_STAY]` напрямую и падает с `KeyError: -1`, убивая эпизод целиком.
    Отсутствие данных означает «действие невозможно», а не «неизвестно».
    """
    entry = focus_action_prob.get(dir8)
    if entry is None:
        return False
    if hasattr(entry, "get"):
        prob = entry.get(action_key)
    else:  # редкий случай: апстрим кладёт в action_prob список
        try:
            prob = entry[action_key]
        except (IndexError, TypeError):
            prob = None
    if prob is None:
        return False
    return action_prob_possible(prob)
'''

CALL = re.compile(
    r"action_prob_possible\(\s*self\.focus\.action_prob\[([^\]]+)\]\[([^\]]+)\]\s*\)")


def main() -> int:
    check = "--check" in sys.argv
    text = TARGET.read_text(encoding="utf-8")
    if "def action_prob_of(" in text:
        print("правка уже применена")
        return 0
    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)

    lines = text.splitlines(keepends=True)
    changed = 0
    out = []
    for line in lines:
        if line.lstrip().startswith("#"):
            out.append(line)
            continue
        new, n = CALL.subn(r"action_prob_of(self.focus.action_prob, \1, \2)", line)
        changed += n
        out.append(new)
    text = "".join(out)

    anchor = "from civrealm.freeciv.units.action_dialog import action_prob_possible, encode_building_id\n"
    if anchor not in text:
        print("Не найден якорь для вставки помощника", file=sys.stderr)
        return 2
    text = text.replace(anchor, anchor + HELPER.lstrip("\n"), 1)

    print(f"заменено обращений: {changed}")
    if check:
        return 0
    TARGET.write_text(text, encoding="utf-8")
    diff = subprocess.run(["diff", "-u", str(BACKUP), str(TARGET)],
                          capture_output=True, text=True)
    PATCH.write_text(diff.stdout, encoding="utf-8")
    print(f"патч сохранён: {PATCH}  ({len(diff.stdout.splitlines())} строк)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())