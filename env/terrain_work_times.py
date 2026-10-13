"""Времена работ по террейну — ПРАВИЛА МИРА, а не наши догадки.

Источник: установленные правила набора `classic` в контейнере стенда
(`/home/docker/freeciv/share/freeciv/classic/terrain.ruleset`);
поля — из исходника его же движка (`common/terrain.h:215-227` закреплённого коммита).

Ноль в правилах означает «работу здесь делать нельзя», поэтому нулевые поля не выписаны:
иначе «нельзя» выглядело бы как «мгновенно» и портило бы дисконт по срокам
(`amortize(total, delay)`, `server/advisors/autoworkers.c:375`).

Перечитать: `.venv/bin/python scripts/read_terrain_work_times.py`
"""

from __future__ import annotations

#: террейн → работа → число ходов.
TERRAIN_WORK_TIMES: dict[str, dict[str, int]] = {
    "desert": {"irrigation": 5, "mine": 5, "road": 2, "transform": 24},
    "forest": {"cultivate": 5, "plant": 15, "road": 4, "transform": 24},
    "glacier": {"mine": 10, "road": 4, "transform": 24},
    "grassland": {"irrigation": 5, "plant": 10, "road": 2, "transform": 24},
    "hills": {"irrigation": 10, "mine": 10, "road": 4, "transform": 24},
    "jungle": {"cultivate": 15, "plant": 15, "road": 4, "transform": 24},
    "lake": {"transform": 36},
    "mountains": {"mine": 10, "road": 6, "transform": 24},
    "ocean": {"transform": 36},
    "plains": {"irrigation": 5, "plant": 15, "road": 2, "transform": 24},
    "swamp": {"cultivate": 15, "plant": 15, "road": 4, "transform": 36},
    "tundra": {"irrigation": 5, "road": 2, "transform": 24},
}
