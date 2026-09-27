"""Прогноз по DOF-Core: перебор вариантов с перевыводом возможностей.

Модуль не знает ни про CivRealm, ни про карту: все оценки приходят внедрёнными
функциями (`Valuations`), поэтому решающие случаи проверяются синтетикой —
без живого стенда и без сети.
"""
from .options import Candidate, Valuations, candidates          # noqa: F401
from .search import (                                           # noqa: F401
    FORECAST_BEAM,
    FORECAST_GAMMA,
    FORECAST_HORIZON,
    IRREVERSIBLE_PENALTY,
    Choice,
    best_immediate,
    choose,
)
from .state import EPSILON, ForecastState                       # noqa: F401

__all__ = [
    "Candidate", "Valuations", "candidates",
    "Choice", "choose", "best_immediate",
    "FORECAST_GAMMA", "FORECAST_BEAM", "FORECAST_HORIZON", "IRREVERSIBLE_PENALTY",
    "ForecastState", "EPSILON",
]
