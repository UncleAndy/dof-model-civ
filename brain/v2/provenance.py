"""Происхождение факта. Аксиома 5: неизвестное не считается нулём, поэтому у каждого
числа в графе знаний есть происхождение и, где применимо, границы неопределённости.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


def json_default(o: Any) -> Any:
    """Сериализация значений мира: numpy-массивы, BitVector и прочие -> обычные list/int/float."""
    if hasattr(o, "tolist"):
        return o.tolist()
    if o.__class__.__name__ == "BitVector":   # civrealm: from BitVector import BitVector
        return list(o)
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "__iter__"):
        return list(o)
    raise TypeError(f"не сериализуется: {type(o).__name__}")


class Origin(str, Enum):
    """Откуда взялось число."""
    MEASURED = "измерено"      # мир отдал прямо (меню, наблюдение, устав)
    INFERRED = "выведено"      # получено правилом из измеренного (аналогия, формула)
    UNKNOWN = "неизвестно"     # нет данных; число НЕ равно нулю


@dataclass(frozen=True)
class Value:
    """Число с происхождением.

    lo/hi — границы неопределённости. Для MEASURED они совпадают с v (мы знаем точно).
    Для INFERRED задаются явно (разброс по k ближайшим). Для UNKNOWN v не участвует
    в сравнениях — вызывающий код обязан это учитывать (аксиома 5).
    """
    v: Optional[float]
    origin: Origin
    lo: Optional[float] = None
    hi: Optional[float] = None
    source: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.origin is Origin.MEASURED and self.lo is None and self.hi is None:
            object.__setattr__(self, "lo", self.v)
            object.__setattr__(self, "hi", self.v)

    @property
    def comparable(self) -> bool:
        """Можно ли сравнивать это число с другими (аксиома 5: неизвестное — нельзя)."""
        return self.origin is not Origin.UNKNOWN and self.v is not None

    def to_dict(self) -> dict[str, Any]:
        return {"v": self.v, "origin": self.origin.value, "lo": self.lo, "hi": self.hi,
                "source": self.source, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Value":
        return cls(v=d.get("v"), origin=Origin(d["origin"]), lo=d.get("lo"), hi=d.get("hi"),
                   source=d.get("source", ""), note=d.get("note", ""))

    @classmethod
    def measured(cls, v: float, source: str = "", note: str = "") -> "Value":
        return cls(v=v, origin=Origin.MEASURED, source=source, note=note)

    @classmethod
    def inferred(cls, v: float, lo: float, hi: float, source: str = "", note: str = "") -> "Value":
        return cls(v=v, origin=Origin.INFERRED, lo=lo, hi=hi, source=source, note=note)

    @classmethod
    def unknown(cls, source: str = "", note: str = "") -> "Value":
        return cls(v=None, origin=Origin.UNKNOWN, source=source, note=note)

    def __str__(self) -> str:
        if self.origin is Origin.UNKNOWN:
            return "?неизвестно"
        if self.lo == self.hi:
            return f"{self.v} [{self.origin.value}]"
        return f"{self.v} ({self.lo}..{self.hi}) [{self.origin.value}]"