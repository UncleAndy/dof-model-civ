import math
city_gain = math.log(22.125)  # 3.097 — измеренный ln(DoF города)
print(f"ln(DoF города) = {city_gain:.3f}")
print()
print("дистанция | frac=1-d/6 | штраф(1 город) | штраф(2 города, зажат) | перенас. | net(1 гор) | net(2 гор)")
for d in [2.0, 3.0, 3.16, 3.61, 4.0, 5.0, 5.8, 6.0]:
    frac = max(0.0, 1.0 - d/6.0)
    pen1 = city_gain * frac
    pen2 = 2 * pen1
    # перенаселённость (примерно): на d<6 перекрытие зон
    ov = {2.0:0.68, 3.0:0.53, 3.16:0.50, 3.61:0.45, 4.0:0.40, 5.0:0.28, 5.8:0.19, 6.0:0.19}.get(d, 0.2)
    ovp = -math.log(1-ov)
    net1 = city_gain - pen1 - ovp
    net2 = city_gain - pen2 - ovp
    print(f"  {d}  |  {frac:.2f}   |   {pen1:.2f}   |    {pen2:.2f}    |  {ovp:.2f}  |  {net1:+.2f}  |  {net2:+.2f}")