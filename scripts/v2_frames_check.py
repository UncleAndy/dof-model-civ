"""Разбор кадров записи: сколько кадров РАЗЛИЧАЮТСЯ и в какой области идут изменения.

Нужно, чтобы отличить «клиент статичен (не вошёл в партию)» от «игра идёт, но движение мелкое».
"""
from __future__ import annotations

import glob
import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image

dirs = sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1 else
                        "civrealm/logs/screenshots/*"))
if not dirs:
    print("каталогов с кадрами нет")
    raise SystemExit(1)

for d in dirs[-2:]:
    frames = sorted(Path(d).glob("*.png"))
    if not frames:
        print(f"{d}: кадров нет")
        continue
    print(f"\n=== {d}: кадров {len(frames)} ===")
    hashes = {}
    for f in frames:
        h = hashlib.md5(f.read_bytes()).hexdigest()[:10]
        hashes.setdefault(h, []).append(f.name)
    print(f"  различных кадров по содержимому: {len(hashes)} из {len(frames)}")

    # попарная разница соседних кадров и область изменений
    prev = None
    diffs = []
    boxes = []
    for f in frames[:60]:
        arr = np.asarray(Image.open(f).convert("L"), dtype=np.int16)
        if prev is not None and arr.shape == prev.shape:
            d_abs = np.abs(arr - prev)
            diffs.append(float(d_abs.mean()))
            ys, xs = np.where(d_abs > 8)
            if len(xs):
                boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
        prev = arr
    if diffs:
        print(f"  средняя разница соседних кадров: min {min(diffs):.2f}, "
              f"медиана {sorted(diffs)[len(diffs) // 2]:.2f}, max {max(diffs):.2f}")
        if boxes:
            x0 = min(b[0] for b in boxes)
            y0 = min(b[1] for b in boxes)
            x1 = max(b[2] for b in boxes)
            y1 = max(b[3] for b in boxes)
            print(f"  область изменений (объединение): x {x0}..{x1}, y {y0}..{y1} "
                  f"(кадр {arr.shape[1]}x{arr.shape[0]})")
        else:
            print("  изменений выше порога НЕ найдено — кадры почти идентичны")
    print(f"  размер кадра: {Image.open(frames[0]).size}")
    print(f"  имена первых кадров: {[f.name for f in frames[:3]]}")
    print(f"  имена последних кадров: {[f.name for f in frames[-3:]]}")