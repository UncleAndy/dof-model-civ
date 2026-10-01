"""Замер тумана на кадрах записи: доля тёмных (неизвестных) клеток.

Сравнивает кадр из режима «наш вид агента» (туман) с кадром из режима наблюдателя (вся карта
открыта). Если туман работает, у «нашего вида» доля тёмных пикселей заметно выше.
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

from PIL import Image

DARK = 30  # порог «темно» по всем каналам


def stats(path: str) -> dict:
    img = Image.open(path).convert("RGB")
    img = img.resize((img.width // 4, img.height // 4))  # прореживание: 4x быстрее
    px = img.load()
    total = img.width * img.height
    dark = 0
    bright = 0
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = px[x, y]
            if r < DARK and g < DARK and b < DARK:
                dark += 1
            elif r + g + b > 300:
                bright += 1
    return {
        "файл": Path(path).name,
        "размер": Image.open(path).size,
        "тёмных_%": round(100 * dark / total, 1),
        "ярких_%": round(100 * bright / total, 1),
    }


if __name__ == "__main__":
    patterns = sys.argv[1:] or ["civrealm/logs/screenshots/*6313*/*.png",
                                "civrealm/logs/screenshots/*6310*/*.png"]
    for pat in patterns:
        files = sorted(glob.glob(pat))
        if not files:
            print(f"{pat}: кадров нет")
            continue
        for f in [files[0], files[len(files) // 2], files[-1]]:
            print(stats(f))