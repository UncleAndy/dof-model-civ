"""Измеренные факты о мире, которые должны переживать прогон.

Имя файла выбрано так, чтобы не сталкиваться с `env/world_model.py` — там живёт
модель мира агента (приоры, провенанс, петля уточнения). Здесь — узкий склад
**измеренных** чисел, которые нельзя вывести из наблюдения и которые нельзя
выдумывать: их надо замерить (или подсмотреть) и использовать дальше.

Решение пользователя (2026-09-27): «замер (а) + сохранение информации в модель
мира для использования в дальнейшем».

Что складывается:

* **стоимость типа** — `produce_<тип>` сервер предлагает, стоимости в наблюдении
  нет, а срок считается как `ceil((стоимость − shield_stock) / prod_shield)`;
* **опции типа** — сколько возможностей даёт одна единица этого типа.

**Опции типа учатся из живых юнитов.** Пока юнит типа жив, наблюдение отдаёт его
параметры (`type_*`), а по ним считается `unit_options` — то есть опции типа
ИЗВЕСТНЫ. Когда носитель исчезает (основал город), опции исчезают вместе с ним, и
без записи в склад тип становится неоценимым: каталог извлекателя строится из
спецификаций известных технологий и полным не является (измерено: в нём нет
`Settlers` и `Warriors`). Отсюда правило: **что узнали о типе — записать**.

Правила, без которых это превратилось бы в выдумывание:

* **Согласие обязательно.** Стоимость и опции типа — константы мира. Если замеры
  разошлись, склад НЕ отдаёт «среднее»: он отдаёт `None` («не знаем»), и прогноз
  такой тип не предлагает. Усреднять противоречивые замеры — это подгонка.
* **Источник называется.** У каждой записи есть `source` (probe / observed) и `n`.
* **Ничего не считается нулём.** Отсутствие записи — отсутствие данных, и
  вызывающий код обязан это различать (`cost(...) is None`).

Файл — обычный JSON, путь можно задать `DOF_MEASURED_FACTS` или аргументом.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

#: Путь по умолчанию: рядом с проектом, но вне пакета — это данные, не код.
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "measured_facts.json"

#: Сколько последних наблюдений одного факта держим. Склад пополняется каждый ход,
#: и без границы он превратился бы в лог.
MAX_OBSERVATIONS = 50

#: Поля факта, которые склад умеет хранить.
FIELDS = ("cost", "options")


def _agreed(values: list[float]) -> float | None:
    """Согласованное значение или `None`, если замеры спорят.

    Стоимость типа — константа мира. Половина замеров за 30 и половина за 40 — это
    «не знаем», а не 35.
    """
    clean = [round(float(v), 6) for v in values if v is not None]
    if not clean:
        return None
    counts = Counter(clean)
    best, best_n = counts.most_common(1)[0]
    if best_n * 2 <= len(clean) and len(clean) > 1:
        return None
    return float(best)


class MeasuredFacts:
    """Измеренные факты о мире: стоимость и опции типов."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        env_path = os.environ.get("DOF_MEASURED_FACTS")
        self.path = Path(path or env_path or DEFAULT_PATH)
        #: имя типа → {"kind": ..., "cost": [...], "options": [...], ...}
        self.facts: dict[str, dict[str, Any]] = {}
        self.load()

    # ------------------------------------------------------------------ чтение
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        # Совместимость с первой редакцией склада: там был ключ `costs`.
        stored = raw.get("facts") if raw.get("facts") is not None else raw.get("costs")
        if isinstance(stored, dict):
            self.facts = {}
            for key, rec in stored.items():
                if not isinstance(rec, dict):
                    continue
                record = dict(rec)
                if "observations" in record and "cost" not in record:
                    # Первая редакция склада хранила только стоимость.
                    record["cost"] = list(record.pop("observations"))
                self.facts[str(key)] = record

    def save(self) -> None:
        """Записать факты. Атомарно: половина файла хуже его отсутствия."""
        payload = {
            "note": "Измеренные факты о мире. Стоимость и опции типа — константы; "
                    "расходящиеся замеры означают «не знаем», а не среднее.",
            "facts": {name: self.facts[name] for name in sorted(self.facts)},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    def value(self, name: str, field: str) -> float | None:
        """Согласованное значение поля. `None` — не измерено или замеры спорят."""
        rec = self.facts.get(str(name))
        if not isinstance(rec, dict):
            return None
        return _agreed(rec.get(field) or [])

    def cost(self, name: str) -> float | None:
        return self.value(name, "cost")

    def options(self, name: str) -> float | None:
        return self.value(name, "options")

    def agreement(self, name: str, field: str = "cost") -> float:
        """Доля наблюдений, подтверждающих принятое значение (0…1)."""
        rec = self.facts.get(str(name)) or {}
        values = [round(float(v), 6) for v in (rec.get(field) or []) if v is not None]
        if not values:
            return 0.0
        accepted = _agreed(values)
        if accepted is None:
            return 0.0
        return values.count(round(accepted, 6)) / len(values)

    def known(self, field: str = "cost") -> list[str]:
        return sorted(name for name in self.facts
                      if self.value(name, field) is not None)

    def kind_of(self, name: str) -> str | None:
        """Юнит или улучшение — если это вообще известно.

        Из наблюдения класс типа не выводится: каталог извлекателя неполон в обе
        стороны (измерено: в каталоге юнитов нет `Warriors` и `Settlers`, в каталоге
        улучшений нет `Barracks`). Поэтому класс знает только склад — из того, что
        реально наблюдалось или измерялось.

        Клин (действие, роняющее матч) здесь НЕ хранится: для этого в проекте есть
        отдельный реестр `env/wedged.py`, и правило обязано быть одно.
        """
        record = self.facts.get(str(name))
        if not isinstance(record, dict):
            return None
        return record.get("kind")

    # ------------------------------------------------------------------ запись
    def observe_type(self, name: str, *, cost: float | None = None,
                     options: float | None = None, kind: str = "unit",
                     source: str = "observed", turn: int | None = None) -> bool:
        """Записать, что узнали о типе. `None` не записывается (это не факт).

        Возвращает True, если запись состоялась: вызывающий код по этому признаку
        решает, сохранять ли файл (склад обновляется каждый ход, а писать на диск
        каждый ход незачем).
        """
        record = None
        for field, value in (("cost", cost), ("options", options)):
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number <= 0.0:
                continue
            if record is None:
                record = self.facts.setdefault(str(name), {"kind": kind})
                record["kind"] = kind or record.get("kind", "unit")
            series = record.setdefault(field, [])
            series.append(round(number, 6))
            del series[:-MAX_OBSERVATIONS]
            record["source"] = source
            record["n"] = max(len(record.get("cost") or []),
                              len(record.get("options") or []))
            if turn is not None:
                record["last_turn"] = int(turn)
        return record is not None

    def observe_cost(self, name: str, cost: float | None, *, kind: str = "unit",
                     source: str = "probe", turn: int | None = None) -> None:
        """Записать стоимость (совместимость с замерным скриптом)."""
        self.observe_type(name, cost=cost, kind=kind, source=source, turn=turn)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in sorted(set(self.known("cost")) | set(self.known("options"))):
            rec = self.facts.get(name) or {}
            out[name] = {
                "kind": rec.get("kind"),
                "cost": self.cost(name),
                "cost_n": len(rec.get("cost") or []),
                "options": self.options(name),
                "options_n": len(rec.get("options") or []),
                "agreement": round(max(self.agreement(name, "cost"),
                                       self.agreement(name, "options")), 2),
            }
        return out


def cost_from_city(city_record: dict[str, Any]) -> float | None:
    """Стоимость того, что город строит, — из чисел самого города.

    ИЗМЕРЕНО: `prod_process` — это ДОЛЯ готовности, а не выход за ход, поэтому
    `стоимость = shield_stock / prod_process`. Число берётся у мира, а не выводится
    из догадок; срок потом считается как
    `max(1, ceil((стоимость − shield_stock) / prod_shield))`.

    Тип, к которому относится эта стоимость, функция не знает — его обязан назвать
    вызывающий (постановку делал он). Если город переключился на другое, стоимость
    попадёт к чужому типу и склад увидит расхождение — и тогда скажет «не знаем»,
    а не «среднее». Ради этого правило согласия и существует.
    """
    if not isinstance(city_record, dict):
        return None
    try:
        stock = float(city_record.get("shield_stock"))
        process = float(city_record.get("prod_process"))
    except (TypeError, ValueError):
        return None
    if process <= 0.0 or stock <= 0.0:
        return None
    return stock / process


def default_facts() -> MeasuredFacts:
    """Склад измеренных фактов по умолчанию (общий для прогонов)."""
    return MeasuredFacts()
