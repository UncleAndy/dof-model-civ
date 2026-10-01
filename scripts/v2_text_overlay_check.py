"""Проверка нанесённого текста: где он лёг и контрастен ли он.

1) По третям кадра: изменённые пиксели должны быть в ЛЕВОЙ и ПРАВОЙ трети, а СЕРЕДИНА — почти
   нетронутой (требование Andy: колонка не больше трети ширины).
2) Контраст: у светлых глифов должна быть тёмная обводка — считаем пиксели «светлый рядом с тёмным».
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

from PIL import Image

drawn_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge/frames_text/port6319")
orig_pat = sys.argv[2] if len(sys.argv) > 2 else "civrealm/logs/screenshots/*6319*/*.png"

drawn = sorted(drawn_dir.glob("*.png"))
if not drawn:
    sys.exit("нет нанесённых кадров")
f = drawn[len(drawn) // 2]
origs = {Path(p).name: Path(p) for p in glob.glob(orig_pat)}
src = origs.get(f.name)
print(f"кадр: {f.name}; исходник найден: {src is not None}")

img = Image.open(f).convert("RGB")
w, h = img.size
print(f"размер {w}x{h}; треть = {w // 3}px")

if src is not None:
    a = img.load()
    b = Image.open(src).convert("RGB").load()
    thirds = {"левая": (0, w // 3), "середина": (w // 3, 2 * w // 3), "правая": (2 * w // 3, w)}
    print("\nизменённые пиксели по третям (шаг 2):")
    for name, (x0, x1) in thirds.items():
        ch = tot = 0
        for y in range(0, h, 2):
            for x in range(x0, x1, 2):
                tot += 1
                pa, pb = a[x, y], b[x, y]
                if abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2]) > 24:
                    ch += 1
        print(f"  {name}: {ch} из {tot} ({100 * ch / max(1, tot):.2f} %)")

# контраст: светлый глиф рядом с тёмной обводкой в левой и правой трети
def contrast_marks(px, x0, x1):
    bright = dark = 0
    for y in range(0, h, 2):
        for x in range(x0, x1, 2):
            r, g, bb = px[x, y]
            if r > 235 and g > 235 and bb > 235:
                bright += 1
            elif r < 40 and g < 40 and bb < 40:
                dark += 1
    return bright, dark

print("\nконтраст (светлые глифы / тёмная обводка):")
for name, (x0, x1) in (("левая", (0, w // 3)), ("правая", (2 * w // 3, w))):
    br, dk = contrast_marks(img.load(), x0, x1)
    print(f"  {name}: светлых {br}, тёмных {dk} → "
          f"{'контраст есть' if br > 50 and dk > 50 else 'ПРОВЕРИТЬ'}")