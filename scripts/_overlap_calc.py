import math

r_sq = 17  # border_city_radius_sq из устава мира
R = int(math.sqrt(r_sq)) + 1
offsets = [(dx, dy) for dx in range(-R, R + 1) for dy in range(-R, R + 1)
           if dx * dx + dy * dy <= r_sq]
total = len(offsets)

def overlap(dx, dy):
    shared = 0
    for ox, oy in offsets:
        # клетка нового города (ox,oy); расстояние до старого города (dx,dy)
        ddx = abs(dx - ox)
        ddy = abs(dy - oy)
        if ddx * ddx + ddy * ddy <= r_sq:
            shared += 1
    return shared / total

print(f"работовая зона: радиус^2={r_sq}, клеток={total}")
print("дистанция | перекрытие ov | штраф -ln(1-ov)")
for d in range(2, 8):
    ov = overlap(d, 0)
    pen = -math.log(1.0 - min(ov, 0.95))
    print(f"   {d}      |   {ov*100:5.1f}%   |   {pen:.3f}")
