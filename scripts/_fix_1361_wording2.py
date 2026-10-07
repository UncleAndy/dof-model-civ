"""Точная правка §13.61 построчно: снять фразу «за ход у юнита одно действие».

Первая попытка промахнулась мимо переноса строк (фраза осталась — контроль её нашёл). Здесь правка идёт
по строкам: находим строку с «ходов шаг разведки», заменяем блок до «производительной.» включительно.
"""
from pathlib import Path

DOC = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/drafts/DOF_CALIBRATION.md")
lines = DOC.read_text(encoding="utf-8").split("\n")
start = next((i for i, l in enumerate(lines) if "ходов шаг разведки" in l), None)
end = next((i for i, l in enumerate(lines) if start is not None and i >= start and l.strip().endswith("производительной.")), None)
print("строки для замены:", start, "→", end)
if start is None or end is None:
    raise SystemExit("блок не найден — правка не применена")
new_block = [
    "ходов шаг разведки счёту не приносит ничего, а стоит — потому что юнит, уведённый в разведку, не делает",
    "того, что давало городу **чистый прирост щитов** (а мера города растёт только от такого прироста).",
    "Движение в нашей постановке не «дополнительная» деятельность, а **замена** производительной. Оговорка",
    "про темп: за ход актору доступны все его действия, поэтому ограничение «один шаг за ход» — это",
    "требование мира (иначе он не успевает, `server_timeout_handle`), а не свойство игры.",
]
lines[start:end + 1] = new_block
DOC.write_text("\n".join(lines), encoding="utf-8")
text = DOC.read_text(encoding="utf-8")
print("спорная фраза встречается раз:", text.count("за ход у юнита **одно** действие"))
print("исправленный блок:", "чистый прирост щитов" in text)
print("байт:", DOC.stat().st_size)