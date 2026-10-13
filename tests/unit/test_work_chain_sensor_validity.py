"""Нулевое изменение map.output не становится измеренным нулём работы."""
import json
import sys

from scripts.summarize_work_chain import main


def test_legacy_base_only_chain_does_not_measure_improvement(tmp_path, monkeypatch, capsys):
    events = [
        {"kind": "start", "unit": "8", "x": 4, "y": 5, "turn": 1,
         "action": "irrigation", "terrain": "Plains", "output": [1, 1, 0], "extras": []},
        {"kind": "watch", "unit": "8", "x": 4, "y": 5, "turn": 4,
         "action": "irrigation", "terrain": "Plains", "output": [1, 1, 0],
         "terrain_before": "Plains", "output_before": [1, 1, 0],
         "extras": ["Irrigation"], "extras_before": [], "changed": True},
    ]
    trace = tmp_path / "chain.jsonl"
    trace.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_work_chain.py", "--in", str(trace)])
    assert main() == 0
    report = capsys.readouterr().out
    assert "НЕ ИЗМЕРЕНО" in report
    assert "+0.00/+0.00/+0.00" not in report
    assert "завершённых работ в выборке: 1" in report
