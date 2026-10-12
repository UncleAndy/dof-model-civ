"""Опасность и нужда в защитнике — правило встроенного ИИ, не наше.

Зачем. Измерено на 45-м ходу (канал стенда, 6 партий): мы держим **2.2** военных юнита
там, где встроенный ИИ держит **0.1**, и строим юнитов больше него (4.8 против 3.1). Наше
правило (§13.159) ставило военный тип в очередь, если «виден чужой юнит ИЛИ у города нет
защитника» — у трёх соседей-ИИ «виден чужой юнит» почти всегда, и правило молотило войско,
которого сам автор правил в мирной партии почти не строит.

Что делает встроенный ИИ. Он считает ОПАСНОСТЬ конкретного города от конкретных чужих
юнитов: юнит опасен, если он вообще способен напасть и может дойти; сама опасность — его
боевой рейтинг нападения, то есть `attack × hp × firepower / POWER_DIVIDER`.

Источники (движок стенда):

* рейтинг нападения — `server/advisors/advgoto.c:381` (`adv_unittype_att_rating`):
  `base_attack_power(...) * hp * firepower / POWER_DIVIDER`;
* делитель — `server/advisors/advtools.h:32` (`POWER_DIVIDER = POWER_FACTOR * 3`)
  и `common/combat.h:32` (`POWER_FACTOR = 10`) ⇒ 30;
* опасность города и «смертельная опасность» — `ai/default/daimilitary.c`
  (`assess_danger_unit`, `assess_danger`; `city_data->grave_danger = 1` только при реальной
  угрозе либо при handicap — у него `H_DANGER`);
* правило постройки защитника — `ai/default/daicity.c:649`, `658`: защитник нужен, когда
  у города нет защиты И есть смертельная опасность.

**Названное упрощение.** Точно как у него, мы не считаем время пути поиском по карте
(`pf_reverse_map`): берётся расстояние между юнитом и городом и ход юнита. Упрощение
одностороннее — оно может только занизить достижимость, то есть уменьшить нужду в войске,
а не раздуть её.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Из `common/combat.h:32` и `server/advisors/advtools.h:32`.
POWER_FACTOR: int = 10
POWER_DIVIDER: int = POWER_FACTOR * 3      # 30


def attack_rating(attack_strength: float, hp: float, firepower: float) -> float:
    """Рейтинг нападения юнита — формула `adv_unittype_att_rating` (advgoto.c:381)."""
    return float(attack_strength) * float(hp) * float(firepower) / POWER_DIVIDER


@dataclass(frozen=True)
class Threat:
    """Чужой юнит, замеченный нами, вместе с тем, что о нём известно."""

    attack_strength: float
    hp: float
    firepower: float = 1.0
    move_rate: float = 0.0
    distance: int = 0          # расстояние до города (по Чебышёву, в клетках)
    is_foreign: bool = True

    @property
    def rating(self) -> float:
        return attack_rating(self.attack_strength, self.hp, self.firepower)

    def turns_to_reach(self) -> float:
        """Сколько ходов ему идти до города при известном ходе. Нет хода — неизвестно."""
        if self.move_rate <= 0 or self.distance <= 0:
            return 0.0 if self.distance <= 0 else float('inf')
        return self.distance / self.move_rate


def city_danger(threats: list[Threat], *, horizon_turns: float = 10.0) -> float:
    """Суммарная опасность города: только те, кто способен напасть и может дойти.

    Встроенный ИИ именно так и отличает «юнит рядом» от «юнит опасен»: у него
    `attack_danger` требует способности к нападению и достижимости. Скаута без
    нападения и воина за пределами достижимости он опасностью не считает.
    """
    total = 0.0
    for threat in threats:
        if not threat.is_foreign or threat.rating <= 0.0:
            continue
        reach = threat.turns_to_reach()
        if reach > horizon_turns:
            continue
        total += threat.rating
    return total


def needs_defender(danger: float, defenders: int) -> bool:
    """Нужен ли защитник — его правило (daicity.c:649/658): нет защиты И есть опасность.

    Прежнее наше правило требовало защитника при одном ФАКТЕ видимости чужого юнита.
    Его правило требует опасности, достижимой для города, и отсутствия защиты. Именно
    поэтому он в мирной партии держит 0.1 юнита, а мы держали 2.2.
    """
    return danger > 0.0 and defenders <= 0


def defenders_wanted(danger: float, *, defence_rating: float = 0.0,
                     defence_power: float = 0.0) -> int:
    """Сколько защитников нужно, чтобы покрыть опасность.

    Встроенный ИИ сравнивает оборону города с опасностью; мы делаем то же, но без его
    квадратичных оценок: каждый защитник покрывает свою оборонную силу, и берётся
    минимальное число, закрывающее опасность. При неизвестной силе защитника ответ 1 —
    это его же минимум «хотя бы один, раз опасность есть».
    """
    power = defence_rating or defence_power
    if danger <= 0.0:
        return 0
    if power <= 0.0:
        return 1
    need = int(danger // power) + (1 if danger % power else 0)
    return max(1, need)