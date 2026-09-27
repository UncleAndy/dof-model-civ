"""Предсказанное состояние для прогноза: только то, что нужно ветвлению.

**Шкала — число опций, а не нормализованная доля.** DoF сущности здесь ≥ 1
(живая сущность всегда имеет хотя бы одну опцию), а у коллапса — около нуля.
Это принципиально: индекс считается как `Σ ln(DoF)`, и при нормализованных долях
(0…1] логарифм любой сущности отрицателен, поэтому добавление города «ухудшает»
индекс, а правило «действовать только при строгом улучшении» превращается в
запрет действовать. Такая ошибка уже ловилась в проекте (см. навык
`civrealm-tournament`, «Σ ln(DoF) with normalised DoF punishes expansion»), и
здесь шкала выбрана заранее и явно.

Дельты в прогнозе — тоже в шкале индекса (натуральные логарифмы), то есть
приращение `Σ ln(DoF)`.

Состояние НЕ является копией наблюдения. В него входит ровно то, что прогноз умеет
менять: значения сущностей, их позиции, города и множество раскрытых клеток. Всё,
что не меняется (правила, каталоги типов), в состояние не копируется — оно
приходит через внедрённые оценки.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

EPSILON = 1e-6


@dataclass
class ForecastState:
    """Состояние мира в прогнозе."""

    #: id сущности → DoF в ОПЦИЯХ (живая сущность ≥ 1, коллапс ≈ 0)
    dof: dict[str, float] = field(default_factory=dict)
    #: обратима ли сущность (вход вето Аксиомы 3)
    reversible: dict[str, bool] = field(default_factory=dict)
    #: сущности-источники коллапса (их обнуление не считается потерей)
    collapse_sources: set[str] = field(default_factory=set)
    #: позиции юнитов (нужны переходам движения и основания)
    positions: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: id города → позиция
    cities: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: раскрытые клетки (для ценности площадок и для информации)
    revealed: set[tuple[int, int]] = field(default_factory=set)
    #: корневое значение обратимой сущности: по нему определяется «коллапс»
    root_dof: dict[str, float] = field(default_factory=dict)

    def clone(self) -> "ForecastState":
        return ForecastState(
            dof=dict(self.dof),
            reversible=dict(self.reversible),
            collapse_sources=set(self.collapse_sources),
            positions=dict(self.positions),
            cities=dict(self.cities),
            revealed=set(self.revealed),
            root_dof=dict(self.root_dof),
        )

    def index(self) -> float:
        """Индекс системы: `Σ ln(DoF)` по сущностям, кроме источников коллапса.

        Тот же вид, что в ядре: сущность с DoF = 1 индекс не меняет, коллапс уводит
        его далеко вниз. Считается именно логарифм каждой сущности (произведение
        возможностей), а не логарифм суммы.
        """
        return sum(math.log(max(v, EPSILON))
                   for eid, v in self.dof.items()
                   if eid not in self.collapse_sources)

    def collapsed(self) -> list[str]:
        """Обратимые сущности, уведённые в коллапс: вето Аксиомы 3."""
        out = []
        for eid, value in self.dof.items():
            if eid in self.collapse_sources:
                continue
            if not self.reversible.get(eid, False):
                continue
            if value <= EPSILON < self.root_dof.get(eid, 0.0):
                out.append(eid)
        return out

    def alive(self) -> int:
        return sum(1 for eid, v in self.dof.items()
                   if v > EPSILON and eid not in self.collapse_sources)
