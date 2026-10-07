"""Показать и починить «продолжение с места»: ключ должен быть (пара, сид), а не номер пары.

Сначала печатаются оба участка (пропуск и запись строки опыта), затем правка по точным строкам,
затем компиляция и печать изменённого места — чтобы не править вслепую рабочий код.
"""
from pathlib import Path

AB = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_ab_city_norm.py")
lines = AB.read_text(encoding="utf-8").split("\n")

def show(tag: str, idx: list[int]) -> None:
    print(f"── {tag} ──")
    for i in idx:
        if 0 <= i < len(lines):
            print(f"{i + 1:>4}|{lines[i]}")

skip_start = [i for i, l in enumerate(lines) if "done" in l and ("= {}" in l or "get(" in l or "if " in l)]
show("участки со словом done", skip_start)
rec_start = [i for i, l in enumerate(lines) if "per.setdefault" in l or "\"score\"" in l]
show("участки с записью строки", rec_start[:12])

if not skip_start or not rec_start:
    raise SystemExit("участки не найдены — правка не применена")

# Вставляем словарь сидов рядом с первым объявлением done, расширяем условие пропуска и запоминаем сид.
fixed = 0
for i in skip_start:
    if lines[i].strip().startswith("done") and "= {" in lines[i] and "done_seed" not in lines[i]:
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines.insert(i + 1, f"{indent}done_seed = {{}}  # полный ключ продолжения: пара И сид")
        fixed += 1
        break

for i, l in enumerate(lines):
    if "done.get(" in l and "done_seed" not in l and "seed" in lines[max(0, i - 3):i + 3].__str__() + l:
        pass  # участок пропуска ищем ниже по признаку наличия continue рядом
for i, l in enumerate(lines):
    if "done.get(arm)" in l and ":" in l and "done_seed" not in l:
        lines[i] = l.replace("done.get(arm)", "done.get(arm) and done_seed.get(arm) == seed")
        fixed += 1
        break

# Запоминаем сид вместе с записью пары: ищем строку, где в per пишется оценка (не в судье).
for i, l in enumerate(lines):
    if "per.setdefault" in l and "score" in l and i > (skip_start[-1] if skip_start else 0):
        indent = l[:len(l) - len(l.lstrip())]
        lines.insert(i + 1, f"{indent}done_seed[arm] = seed")
        fixed += 1
        break

AB.write_text("\n".join(lines), encoding="utf-8")
print(f"правок внесено: {fixed}")
import py_compile  # noqa: E402
py_compile.compile(str(AB), doraise=True)
print("компиляция: ок")
show("после правки — ключ и пропуск",
     [i for i, l in enumerate(lines) if "done_seed" in l or "done.get(arm)" in l])