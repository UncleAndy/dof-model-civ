"""Где в кадре открытая (не тёмная) область: рамка и центр.

Нужно, чтобы убедиться, что открытый агентом пятачок действительно В КАДРЕ (камера на нашем юните),
а не уехал за край (это была ошибка варианта «камера на центр карты»).
"""
from __future__ import annotations

import glob
import sys

from PIL import Image

DARK = 30


def where(path: str) -> None:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    minx, miny, maxx, maxy = w, h, -1, -1
    sx = sy = cnt = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            r, g, b = px[x, y]
            if not (r < DARK and g < DARK and b < DARK):
                minx, miny = min(minx, x), min(miny, y)
                maxx, maxy = max(maxx, x), max(maxy, y)
                sx += x
                sy += y
                cnt += 1
    if cnt == 0:
        print(f"{path}: кадр полностью тёмный")
        return
    print(f"{path.split('/')[-1]}: кадр {w}x{h}; открытая область x[{minx}..{maxx}] y[{miny}..{maxy}] "
          f"центр открытого ({sx // cnt},{sy // cnt}) при центре кадра ({w // 2},{h // 2})")


if __name__ == "__main__":
    for pat in sys.argv[1:]:
        files = sorted(glob.glob(pat))
        for f in (files[:1] + files[len(files) // 2:len(files) // 2 + 1] + files[-1:]):
            where(f)