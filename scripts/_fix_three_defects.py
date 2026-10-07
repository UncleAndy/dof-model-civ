"""Три правки: переименовать локальную переменную (перекрывала функцию), подключить вызов записи,
сменить слот третьего плеча на живой.

1. `UnboundLocalError: _scout_mode` — имя функции `_scout_mode` перекрыто локальной переменной с тем же
   именем, поэтому вызов читал локальную до её присваивания. Локальная переименована в `_scout_how`.
   Урок дня, который стоит запомнить: имя функции и имя локальной переменной не должны совпадать.
2. Вызов `_record_reveals` не встал, потому что сторож искал подстроку, совпадавшую с определением
   функции. Теперь сторож ищет вызов по отступу и скобке.
3. Плечо C не поднялось на слоте 6008 (`Connection could not be established`) — слот сменил на 6005.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
AB = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_ab_city_norm.py")
text = RUN.read_text(encoding="utf-8")
done: list[str] = []

if "        _scout_mode = (_scout_mode()" in text or "_scout_mode = (_scout_mode()" in text:
    text = text.replace("_scout_mode = (_scout_mode() or \"idle-only\")",
                        "_scout_how = (_scout_mode() or \"idle-only\")", 1)
    text = text.replace("_scout_mode == \"settler-first\"", "_scout_how == \"settler-first\"", 1)
    text = text.replace("_scout_mode == \"idle-only\"", "_scout_how == \"idle-only\"", 1)
    done.append("локальная переменная переименована в _scout_how")

lines = text.split("\n")
already = any(l.strip().startswith("_record_reveals(obs") for l in lines)
if not already:
    idx = next((i for i, l in enumerate(lines) if l.strip() == "_LAST_TURN = turn"), None)
    if idx is None:
        idx = next((i for i, l in enumerate(lines) if "_DRIVER.new_turn()" in l), None)
    if idx is None:
        raise SystemExit("место для вызова записи не найдено")
    indent = lines[idx][:len(lines[idx]) - len(lines[idx].lstrip())]
    lines.insert(idx + 1, f'{indent}_record_reveals(obs, (info or {{}}).get("turn"), V.RUN_TAG)')
    text = "\n".join(lines)
    done.append("вызов записи открытий подключён")
else:
    done.append("вызов записи уже есть")

RUN.write_text(text, encoding="utf-8")
ab = AB.read_text(encoding="utf-8")
if 'default=6008' in ab:
    ab = ab.replace('default=6008', 'default=6005', 1)
    AB.write_text(ab, encoding="utf-8")
    done.append("слот третьего плеча 6008 → 6005")

print("правки:", "; ".join(done))
import py_compile  # noqa: E402
for p in (RUN, AB):
    py_compile.compile(str(p), doraise=True)
print("компиляция: ок")
for i, l in enumerate(RUN.read_text(encoding="utf-8").split("\n"), 1):
    if "_record_reveals(obs" in l or "_scout_how" in l:
        print(f"{i:>4}|{l}")