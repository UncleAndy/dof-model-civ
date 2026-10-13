"""Тип дороги — секция road_*, а не extra_* (classic terrain.ruleset)."""
import runpy

from scripts import read_terrain_work_effects as export


def test_export_reads_road_type_section(monkeypatch, tmp_path):
    rules = '''[terrain_grassland]
road_trade_incr_pct = 100
[extra_road]
name = "Road"
[road_road]
extra = "Road"
trade_incr = 1
[road_railroad]
extra = "Railroad"
shield_bonus = 50
'''
    destination = tmp_path / "effects.py"
    monkeypatch.setattr(export, "read_ruleset", lambda: rules)
    monkeypatch.setattr(export, "OUT", destination)
    export.main()
    table = runpy.run_path(str(destination))["ROAD_EFFECTS"]
    assert table["road"]["trade_incr"] == 1
    assert table["railroad"]["shield_bonus"] == 50
