"""Конформность ядра DOF-Core v0.11 (`brain/spec`) — прогон эталонного харнесса.

Харнесс `brain/spec/harness_v011.py` — часть эталона и НЕ меняется: он проверяет
утверждения §7 (в текущем порте — 112 проверок). Тест запускает его подпроцессом и
требует нулевых падений, чтобы конформность ядра проверялась автоматически, а не на словах.

Второй тест — дешёвая проверка, что подключён именно ожидаемый контракт: замороженный
порядок линз (§4.6) и общие константы ядра.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_spec_v011_harness_passes() -> None:
    """§7: эталонный харнесс v0.11 проходит без падений."""
    proc = subprocess.run(
        [sys.executable, "-m", "brain.spec.harness_v011"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    out = proc.stdout or ""
    assert "failures: 0" in out, f"харнесс v0.11 упал (rc={proc.returncode}):\n{out}\n{proc.stderr}"
    assert proc.returncode == 0, f"харнесс вернул rc={proc.returncode}:\n{out}"


def test_spec_contract_surface() -> None:
    """§4.6 и §4.5: замороженный порядок линз и общие константы ядра."""
    from brain.spec.calculus_core import NET_DELTA_TOLERANCE, OBSERVED_HYPOTHESIS_ID
    from brain.spec.measurement import LENS_ORDER

    assert LENS_ORDER == ("variety", "options", "constraint")
    assert NET_DELTA_TOLERANCE > 0.0
    assert OBSERVED_HYPOTHESIS_ID  # зарезервированный id наблюдаемого состояния