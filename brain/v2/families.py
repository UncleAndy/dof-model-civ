"""Семейства действий (решение D1, объявлено до данных).

Мир параметризует имена: `goto_0..7` — одно действие в восьми направлениях;
`research_tech_Code of Laws_13` — выбор технологии; `set_sci_lux_tax_0_40_60` — раскладка
налог/роскошь/наука; `hut_enter_6` — вход в хижину.

Считать их разными возможностями нельзя: тогда DoF раздут механическими повторами, и
«различность» путей фиктивна (спека прямо предупреждает о такой ловушке). Поэтому у действия
есть **семейство** — имя без хвостовых параметров.

Правило: берём токены имени через `_` и отбрасываем хвост, начиная с первого токена, который
либо число, либо имя собственное (с заглавной). Всё, что осталось, — семейство.

    goto_0                     -> goto
    build_city                 -> build_city      (не сливается с build_road)
    build_road                 -> build_road
    hut_enter_6                -> hut_enter
    research_tech_Code of Laws_13 -> research_tech
    set_sci_lux_tax_0_40_60    -> set_sci_lux_tax
    change_gov_Anarchy         -> change_gov
    keep_activity              -> keep_activity
"""
from __future__ import annotations

from typing import Iterable


def action_family(name: str) -> str:
    """Семейство действия: имя без числовых и именных хвостовых параметров."""
    tokens = str(name).split("_")
    keep: list[str] = []
    for tok in tokens:
        if not tok:
            break
        if tok.isdigit():
            break
        if tok[:1].isupper():
            break
        keep.append(tok)
    return "_".join(keep) if keep else str(name)


def family_of_options(options: Iterable[str]) -> dict[str, list[str]]:
    """Семейство -> конкретные варианты, встреченные в меню."""
    out: dict[str, list[str]] = {}
    for o in options:
        out.setdefault(action_family(o), []).append(o)
    return {k: sorted(v) for k, v in out.items()}


def family_counts(options: Iterable[str]) -> dict[str, int]:
    return {k: len(v) for k, v in family_of_options(options).items()}