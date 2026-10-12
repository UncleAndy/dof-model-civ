"""Сторожа работы по клетке — под новый порядок источников (§13.257-13.258).

Было: «не измерено → None». Стало: «измерено нами → наши данные; иначе правила мира; иначе None».
Смысл сторожей сохранён (незнание не притворяется нулём), но добавлен третий источник и его метка.
"""
from __future__ import annotations

import pathlib

P = pathlib.Path("/home/hermes/projects/AI/DOF-MODEL-CIV/tests/unit/test_terrain_work.py")
src = P.read_text(encoding="utf-8")

OLD_1 = '''    def test_unmeasured_extra_returns_none_not_zero(self):
        # Mine пока не измерена: это НЕ «эффекта нет», а «не знаем». Разница
        # важна: неизмеренное обязано молчать, а не притворяться нулём.
        assert tile_effect("Mine", "Hills", (), self.VALS) is None'''
NEW_1 = '''    def test_unknown_to_both_sources_is_none_not_zero(self):
        # Экстры, которой нет ни в наших измерениях, ни в правилах мира, мы
        # действительно не знаем: обязана молчать, а не притворяться нулём.
        assert tile_effect("NoSuchExtra", "Grassland", (), self.VALS) is None

    def test_unmeasured_extra_falls_back_to_world_rules(self):
        # Шахта на холме у нас не измерена, но правила мира её знают:
        # `[terrain_hills] mining_shield_incr = 3` (classic/terrain.ruleset).
        # Именно этим заполняется незнание, из-за которого цена работы была нулём (§13.257).
        assert tile_effect("Mine", "Hills", (), self.VALS) == (0.0, 3.0, 0.0)
        assert tile_effect("Mine", "Desert", (), self.VALS) == (0.0, 1.0, 0.0)

    def test_source_of_the_number_is_reported(self):
        # Решение должно быть проверяемым: откуда взято число — наши измерения или правила.
        ours, world = [], []
        tile_effect("Coal", "Hills", (), self.VALS, source=ours)
        tile_effect("Mine", "Hills", (), self.VALS, source=world)
        assert ours == ["измерено"]
        assert world == ["правила мира"]'''
assert OLD_1 in src, "первый сторож не найден"
src = src.replace(OLD_1, NEW_1, 1)

OLD_2 = '''        assert tile_effect("Irrigation", "Grassland", (), self.VALS) == (0.0, 0.0, 0.0)
        # А на пустыне это НЕ измерено — и потому не обобщается.
        assert tile_effect("Irrigation", "Desert", (), self.VALS) is None'''
NEW_2 = '''        assert tile_effect("Irrigation", "Grassland", (), self.VALS) == (0.0, 0.0, 0.0)
        # Расхождение источников (§13.258): замер дал ноль, а правила classic обещают
        # +1 пищу. Пока расхождение не разрешено, приоритет у НАШЕГО замера — и сторож
        # это фиксирует, чтобы «удобное» число не подменило измеренное молча.
        assert tile_effect("Irrigation", "Desert", (), self.VALS) == (1.0, 0.0, 0.0), (
            "пустыня: измерения нет, значит берём правила мира (irrigation_food_incr = 1)"
        )'''
assert OLD_2 in src, "второй сторож не найден"
src = src.replace(OLD_2, NEW_2, 1)

OLD_3 = '''        assert tile_effect("Road", "Forest", (), self.VALS) is None'''
NEW_3 = '''        # Лес: своих приростов у дороги в правилах нет, значит и добавить нечего —
        # ноль ЭТО ЗНАНИЕ, а не «не знаем» (совпало с живым замером на Plains).
        assert tile_effect("Road", "Forest", (), self.VALS) == (0.0, 0.0, 0.0)'''
assert OLD_3 in src, "третий сторож не найден"
src = src.replace(OLD_3, NEW_3, 1)

P.write_text(src, encoding="utf-8")
print("сторожа работы по клетке приведены к порядку источников")
