"""DOF-Core v0.11 — эталонный калькулятор (Python-порт), вложенный в проект.

PROVENANCE
----------
Источник:   репозиторий DOF-CORE (NousResearch/DOF), каталог `patterns/python`.
Коммит:     97e12f9ec163c34c43532b60d80ba93dac40f874 (`v0.11-1-g97e12f9`, тег `v0.11`).
Лицензия:   CC BY-SA 4.0 (см. DOF-SPEC §2).
Правка:     только строки импорта — «плоские» имена эталона заменены на относительные
            (`from measurement import …` → `from .measurement import …`), см.
            `scripts/_spec_imports_fix.py`. Математика не менялась.

Файлы порта:
    calculus_core.py   — ядро §4: индекс, `calc`, источник коллапса, предикат §4.5,
                         гейты §4.8/§4.8b, условная оценка §4.10, отчёт §6
    measurement.py     — слой измерения (§4.6): линзы ψ_var·ψ_opt·ψ_con, декларация, дайджесты
    world_graph.py     — наблюдаемый граф мира (§3.5): act/exchange/measure, пути, замыкания
    hypothesis.py      — набор гипотез (§3.6/§4.10)
    orchestrator.py    — контур цикла: генератор → ядро → отчёт
    generator.py       — интерфейс генератора (§9, informative)
    graph_mapper.py    — построение графа мира
    fixture_v07.py, fixture_v011.py, options_v07.py, harness_v011.py — фикстуры и конформный
                         харнесс (112 проверок §7)

Конформность ядра доказывается его же харнессом, см. `tests/test_spec_conformance.py`.
"""

__all__ = [
    "calculus_core",
    "measurement",
    "world_graph",
    "hypothesis",
    "orchestrator",
    "generator",
    "graph_mapper",
    "fixture_v07",
    "fixture_v011",
    "options_v07",
]