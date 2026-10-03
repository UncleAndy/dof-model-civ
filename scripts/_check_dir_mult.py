import sys
sys.path.insert(0, '/home/hermes/projects/AI/DOF-MODEL-CIV')
from brain.v2.horizon import K_NEAR, TABU_DEPTH, direction_multiplier

class E:
    def __init__(self, attrs): self.attrs = attrs; self.kind='unit'; self.name='Explorer'
class G:
    def __init__(self, e, world): self._e=e; self.world=world
    def entity(self, eid): return self._e

# юнит в (5,5), история: (5,5),(6,5),(6,6),(7,6) — последние 3: (6,5),(6,6),(7,6)
attrs = {"x":5,"y":5,"история_клеток":[(5,5),(6,5),(6,6),(7,6)]}
g = G(E(attrs), {"xsize":80})
# goto_4 = (1,0) → (6,5) — была недавно 1 раз
for act in ["goto_4","goto_6","goto_2"]:
    k, why = direction_multiplier(g, "1", act)
    print(act, "->", round(k,3), why or "(свежая, k=1)")

print()
print("Проверка выхода из тупика: если ВСЕ направления ведут на недавние клетки —")
attrs2 = {"x":5,"y":5,"история_клеток":[(5,5),(6,5),(4,5),(5,6)]}
g2 = G(E(attrs2), {"xsize":80})
for act in ["goto_4","goto_3","goto_6"]:
    k, why = direction_multiplier(g2, "1", act)
    print(" ", act, "-> k =", round(k,3))
print("Вывод: k>0 у всех — значит движение возможно, выбирается наименее штрафуемое (не запрет).")