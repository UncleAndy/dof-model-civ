"""Чтение полей наблюдения: numpy-скаляры и массивы.

Регресс: `truthy()` возвращал `bool(size)`, то есть ЛЮБОЙ numpy-скаляр (включая
`np.False_`) считался истинным. Из-за этого список флагов города (`improvements`)
читался как «все 68 истинны» вместо реальных 21, первый множитель города всегда
упирался в потолок, и развитый город переставал отличаться от голого.
"""
from __future__ import annotations

import numpy as np

from env.entity_extractor import truthy


class TestNumpyTruthiness:
    def test_numpy_scalars_are_read_by_value(self):
        assert truthy(np.False_) is False
        assert truthy(np.True_) is True
        assert truthy(np.int64(0)) is False
        assert truthy(np.int64(7)) is True
        assert truthy(np.float64(0.0)) is False

    def test_arrays_are_true_only_if_any_element_is_set(self):
        assert truthy(np.zeros(68, dtype=bool)) is False
        assert truthy(np.array([False, False, True])) is True
        assert truthy(np.zeros((2, 3))) is False

    def test_plain_python_values_unchanged(self):
        assert truthy(None) is False
        assert truthy(True) is True
        assert truthy({}) is False
        assert truthy({"dest_x": 4}) is True
        assert truthy([]) is False
        assert truthy([1]) is True

    def test_a_flag_list_counts_only_the_set_entries(self):
        flags = [True] * 21 + [False] * 47
        assert sum(1 for v in flags if truthy(np.bool_(v))) == 21
