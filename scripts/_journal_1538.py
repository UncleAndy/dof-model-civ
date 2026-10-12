"""13.238: retsept upravlyayushchego - nomera paketov i polya proverены dvumya istochnikami."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAL = ROOT / "drafts" / "DOF_CALIBRATION.md"

SECTION = """
### 13.238 Рецепт управления городским управляющим: номера пакетов и поля сверены дважды

**Зачем.** §13.237 нашёл, что мир принимает `PACKET_WEB_CMA_SET { id; cm_parameter }`, а в обёртке
стенда этого пакета нет — поэтому раскладку наших городов выбирает умолчание
(`set_default_city_manager`), а не наши требования. Собрал рецепт целиком, чтобы правка не гадала.

**Номера пакетов — сверены ДВУМЯ независимыми источниками:**

1. в обёртке стенда: `civrealm/.../utils/version/v14.py` — соглашение `packet_<имя> = <номер>`;
2. в клиенте веба: `/docker/freeciv-web/target/freeciv-web/javascript/packets.js:75-76` —
   `var packet_web_cma_set = 257; var packet_web_cma_clear = 258`.

Число `257`/`258` получилось и разбором `enum packet_type` из `common/packets_gen.h`; способ проверен
на известном пакете: `PACKET_CITY_MAKE_SPECIALIST` даёт **37**, ровно как в обёртке. Итого:

* `PACKET_WEB_CMA_SET = 257`
* `PACKET_WEB_CMA_CLEAR = 258`

**Поля `cm_parameter` — из `common/aicore/cm.h:40-49` (порядок объявления):**

    int  minimal_surplus[O_LAST];   /* 6: food, shield, trade, gold, luxury, science */
    bool max_growth;
    bool require_happy;
    bool allow_disorder;
    bool allow_specialists;
    int  factor[O_LAST];            /* те же 6 */
    int  happy_factor;

**Форма запроса — из самого клиента (там же, где живёт интерфейс управляющего):**
`javascript/cma.js:115`:

    var packet = {"pid": packet_web_cma_set, "id": city_id, "cm_parameter": cm_parameter};
    send_request(JSON.stringify(packet));

**Путь отправки у нас есть.** Обёртка держит соединение на контроллере:
`civ_controller.py:132` — `self.ws_client = CivConnection(self.host, self.client_port)`, а отправка —
`connectivity/civ_connection.py:119` — `send_request(packet_payload, wait_for_pid=None)`. Мы достаём
контроллер так же, как уже делаем это для классов юнитов:
`getattr(env.unwrapped, "civ_controller")`.

**Что отправлять (числа — из мира, `set_default_city_manager`, `cityturn.c:313-360`).** Для города
размера 1 мир ставит: `factor[O_FOOD] = 20`, `factor[O_SHIELD] = 5`, `factor[O_GOLD] = 2`,
`factor[O_SCIENCE] = 2`, `factor[O_TRADE] = 0`, `factor[O_LUXURY] = 0`, `minimal_surplus[O_FOOD] = 1`
(и 0, если житница полна), `minimal_surplus[O_SHIELD] = 1`, `require_happy = FALSE`,
`allow_disorder = FALSE`, `allow_specialists = TRUE`. Наша правка — **потребовать прирост еды 2**
вместо 1 при размере 1 (то есть то же требование, но строже: рост города важнее щита), остальные
числа брать его же, не выдумывать.

**Следующий шаг (объявлен до данных).** Отправлять `packet_web_cma_set` на каждый свой город при
смене размера или раз в N ходов (не каждый ход — незачем), затем та же форма замера: шесть партий
по 30 ходов, след `DOF_TRACE_UNITS=1`. Порог вердикта: городов ≥ 4 к 30-му ходу (сейчас медиана 2,
у него 5), и прирост еды перестаёт быть нулевым (сейчас чередование +2/+0). Ожидание: управляющий
держит требуемое, приказ по клетке больше не нужен вовсе, и ходы освобождаются под основание.
"""


def main() -> None:
    text = CAL.read_text(encoding="utf-8")
    if "### 13.238 Рецепт управления городским управляющим" in text:
        print("раздел 13.238 уже записан")
        return
    CAL.write_text(text.rstrip() + "\n" + SECTION.rstrip() + "\n", encoding="utf-8")
    print("раздел 13.238 записан | знаков:", len(CAL.read_text(encoding="utf-8")))


main()