"""13.218: Barracks/Coinage - kak oni ustroeny i chego ne hvataet diya ocenki."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"

SECTION = """
### 13.218 Почему `Barracks` и `Coinage` не оценены — и что для этого нужно

**Как устроен `Barracks` (измерено на правилах мира).** У него НЕТ собственных эффектов: он
работает через флаг, и это видно в `classic/effects.ruleset`:

```
[effect_barracks_veteran]  type = "Veteran_Build"  value = 1
    reqs: "BuildingFlag", "Barracks", "City", TRUE
          "UnitClass",    "Land",     "Local", TRUE
          "UnitFlag",     "NonMil",   "Local", FALSE
[effect_barracks_regen]    type = "HP_Regen"       value = 100
    reqs: "BuildingFlag", "Barracks", "City", TRUE
          "UnitClass",    "Land",     "Local", TRUE
```

То есть постройка ценна не «своим» эффектом, а тем, что включает чужие. Наша таблица эффектов
хранит требования по цели (здание/юнит/наука) и потому про `BuildingFlag` не знает — отсюда и
пустая выдача по `Barracks`: не «ценность ноль», а ценность НЕ ПРОЧИТАНА. Это надо назвать
честно: пробел в картине мира, а не свойство постройки.

**Его числа для этих семейств — найдены и цитируются** (`ai/default/daieffects.c`):

* `EFT_HP_REGEN` / `EFT_HP_REGEN_2` (`:441`): `v += 5 * c + num_affected_units(...)`;
* `EFT_MIN_HP_PCT` (`:451`): `v += 3 * c + num`;
* `EFT_VETERAN_COMBAT` (`:452`): `v += 2 * c + num`;
* `EFT_VETERAN_BUILD` (`:457`): `v += amount * (3 * c + num)`, где `amount` — величина эффекта
  (у `Barracks` это 1);
* `EFT_MOVE_BONUS` (`:433`): `v += 8 * v * amount + num`.

Здесь `c` — это размер города у него, а `num_affected_units(peffect, adv)` — счётчик СВОИХ юнитов,
на которых эффект действует. Второе — не догадка, а его функция, и её семантику надо прочитать
перед портом: считать «все наши военные» вместо «те, на кого эффект действует» значило бы
выдумать число, а не взять его.

**`Coinage`** собственных эффектов не имеет вовсе (в правилах он не упоминается) и цены в
`buildings.ruleset` тоже нет: это перевод щитов в золото, а не постройка-эффект. Его оценка у него
идёт не через эффекты, и это отдельный пункт.

**Объявленный следующий шаг (до данных).** (1) Дополнить таблицу эффектов требованиями-флагами
(`BuildingFlag`, `UnitClass`, `UnitFlag`) — тогда `Barracks` перестанет быть «не прочитанным».
(2) Прочитать `num_affected_units` в его коде и портировать её семантику, а не подставлять своё
число. (3) После этого — проверить, сдвигается ли выбор постановки с `Warriors` хотя бы иногда.
Ожидание: сдвинется, когда доступная постройка даёт больше ценности, чем живой военный юнит в
очереди; если не сдвинется, значит рычаг не в оценке, а в наборе доступного (наука).
"""


def main() -> None:
    text = CAL.read_text(encoding="utf-8")
    if "### 13.218 Почему `Barracks`" in text:
        print("раздел 13.218 уже записан")
    else:
        CAL.write_text(text.rstrip() + "\n" + SECTION.rstrip() + "\n", encoding="utf-8")
        print("раздел 13.218 записан | знаков:", len(CAL.read_text(encoding="utf-8")))


main()