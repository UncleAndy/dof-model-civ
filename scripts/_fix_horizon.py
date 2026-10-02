import io

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/brain/v2/horizon.py'
with io.open(path, encoding='utf-8') as f:
    lines = f.readlines()

# строки 365-369 (индекс 364-368) — исправить отступ и формат
fix = [
    '    if d_min is not None and d_min < CITY_SPACING:\n',
    '        d_safe = max(d_min, 0.5)   # поселенец на клетке города (d=0) → считаем как 0.5\n',
    '        spacing_pen = -math.log(d_safe / float(CITY_SPACING))\n',
    '        why_spacing = (f"разнос: ближайший свой город на дистанции {d_min:.1f} < "\n',
    '                       f"{CITY_SPACING} → −{spacing_pen:.3f}")\n',
]
lines[364:369] = fix

with io.open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('OK')
