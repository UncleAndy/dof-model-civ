"""Исправить порядок: хук `V011_SCOUT` должен стоять ПОСЛЕ `global`, иначе `_SOURCE` читается
до объявления (SyntaxError: name '_SOURCE' is used prior to global declaration) — ровно это и
поймал `py_compile`, поэтому правка не ушла в прогон.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
G = "    global _DRIVER, _LAST_TURN, _PREV_OBS, _SOURCE\n"

text = RUN.read_text(encoding="utf-8")
first = text.find(G)
if first < 0:
    raise SystemExit("строка global не найдена")
second = text.find(G, first + len(G))
if second < 0:
    print("дублирующей строки global нет — похоже, уже исправлено")
else:
    # Вырезаем вставленный кусок (он лежит между двумя `global`) и возвращаем его ПОСЛЕ второго.
    block = text[first + len(G):second]
    text = text[:first] + G + block + text[second + len(G):]
    RUN.write_text(text, encoding="utf-8")
    print("переставлено: хук теперь после global")

print("── проверка компиляции ──")
import py_compile  # noqa: E402
for p in ("scripts/v011_live_run.py", "scripts/v011_ab_city_norm.py"):
    py_compile.compile(str(RUN.parent.parent / p), doraise=True)
    print(f"{p}: ок")
print("── где теперь хук ──")
lines = RUN.read_text(encoding="utf-8").splitlines()
for i, l in enumerate(lines, 1):
    if "V011_SCOUT" in l or l.strip() == "global _DRIVER, _LAST_TURN, _PREV_OBS, _SOURCE":
        print(f"{i:>4}|{l}")