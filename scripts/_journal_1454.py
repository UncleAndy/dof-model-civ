"""13.154: gde lezhit kod shtatnogo II stenda."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"

SECTION = """
### 13.154 Где лежит код штатного ИИ стенда (найдено по запросу владельца)

**Владелец:** «Я считаю что проблема в том, что наш агент банально не умеет играть… найти в проекте
(`AI/civrealm`) код реализации стандартного ИИ игрока стэнда».

**Первое, что важно: в самом проекте `AI/civrealm` кода ИИ нет.** В нём **ноль** C-файлов. Python-часть проекта
делает только три вещи:

* запускает партию: `src/civrealm/freeciv/misc/modified_server_code/publite2.py` и
  `pubscript_multiplayer.serv` (там `set aifill 8`, `set autotoggle enabled` и прочее);
* включает ИИ и задаёт ему уровень: `src/civrealm/freeciv/players/player_ctrl.py:226` —
  `["aitoggle", "novice", "easy", "normal", "hard"]`;
* содержит **своих** агентов — это Python-клиенты: `src/civrealm/agents/` (`base_agent.py`,
  `controller_agent.py`, `no_op_agent.py`, `random_agent.py`, `random_language_agent.py`). Наш агент с принципом
  DoF работает именно как такой клиент, то есть **рядом** со штатным ИИ, а не вместо него.

**Штатный ИИ — это встроенный ИИ Freeciv (C), и его код лежит в контейнере стенда:**

* `/docker/freeciv/freeciv/ai/default/` — нынешний ИИ: `daicity.c`, `daidomestic.c`, `daimilitary.c`,
  `daidiplomacy.c`, `daihunter.c`, `daidata.c`, `daiactions.c`, `daieffects.c`, а также `aiferry.c`,
  `aiguard.c`, `aihand.c`, `aiair.c`, `aidiplomat.c`, `aiparatrooper.c`;
* `/docker/freeciv/freeciv/ai/classic/classicai.c` — прежний ИИ;
* `/docker/freeciv/freeciv/ai/difficulty.c` — уровни сложности, `ai/handicaps.c` — надбавки и ограничения;
* собрано в бинарь `/home/docker/freeciv/bin/freeciv-web` (в нём видны символы `ai_choose`, `ai_level`,
  `aitoggle`); дерево под git, свежий коммит — «Refine AI assistant».

**Что именно даёт уровень `normal` (это важно для честности сравнения) — из `ai/difficulty.c`:**

| величина | значение на `normal` |
|---|---|
| `fuzzy` (случайность решений) | **0** — ИИ не «ошибается» наугад |
| `expansionism` (склонность к новым городам) | **100** — обычная, как у «человека» |
| `science_cost` | 100 — эталон «как у человека» |
| надбавки/ограничения (`handicaps`) | H_RATES, H_TARGETS, H_HUTS, H_DIPLOMAT, H_CEASEFIRE, H_NOBRIBE_WF |

То есть `normal` — это **не усиленный ИИ, а скорее ограниченный** (у `hard`/`cheating` ограничений почти нет).
Значит наше отставание впятеро — это не «ему выдали бонусы», а именно разница в умении играть. Тем самым
предположение владельца подтверждается кодом, а не мнением.
"""


def main() -> None:
    text = CAL.read_text(encoding="utf-8")
    if "### 13.154 Где лежит код штатного ИИ" in text:
        print("раздел 13.154 уже записан")
    else:
        CAL.write_text(text.rstrip() + "\n" + SECTION.rstrip() + "\n", encoding="utf-8")
        print("раздел 13.154 записан | знаков:", len(CAL.read_text(encoding="utf-8")))


main()