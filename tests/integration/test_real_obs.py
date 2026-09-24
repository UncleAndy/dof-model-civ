"""
Integration tests: validate entity_extractor against real CivRealm observations.

Requires:
- Freeciv-web Docker running (see scripts/setup.sh)
- Captured observations in tests/fixtures/real_obs_01.json (see scripts/capture_obs.py)

If observations are not available, tests are skipped.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from env.entity_extractor import GameStateExtractor, compute_total_dof_index

# ── Skip condition ────────────────────────────────────────────────────────────

OBS_FILE = Path("tests/fixtures/real_obs_01.json")

requires_observations = pytest.mark.skipif(
    not OBS_FILE.exists(),
    reason=f"Real observations not found at {OBS_FILE}. Run: .venv/bin/python scripts/capture_obs.py",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_observations() -> list[dict]:
    """Load captured observations from JSON file."""
    with open(OBS_FILE) as f:
        return json.load(f)


# ── Tests ─────────────────────────────────────────────────────────────────────

@requires_observations
class TestRealObservationExtraction:
    """Validate extractor against real CivRealm observations."""

    @pytest.fixture
    def snapshots(self) -> list[dict]:
        return load_observations()

    @pytest.fixture
    def extractor(self) -> GameStateExtractor:
        return GameStateExtractor(my_player_id=0)

    def test_extraction_does_not_crash(self, snapshots, extractor):
        """All snapshots should be extractable without errors."""
        for snap in snapshots:
            result = extractor.extract(snap["observation"], snap["info"], snap["turn"])
            assert result is not None
            assert result.state is not None

    def test_dof_values_in_valid_range(self, snapshots, extractor):
        """All DoF values should be in [0, 1]."""
        for snap in snapshots:
            result = extractor.extract(snap["observation"], snap["info"], snap["turn"])
            for entity in result.state.entities.values():
                assert 0.0 <= entity.current_dof <= 1.0, f"{entity.entity_id}: DoF={entity.current_dof}"

    def test_psi_digest_deterministic_real_data(self, snapshots, extractor):
        """Psi digest should be deterministic across extractions."""
        if not snapshots:
            pytest.skip("No snapshots to test")
        snap = snapshots[0]
        result1 = extractor.extract(snap["observation"], snap["info"], snap["turn"])
        result2 = extractor.extract(snap["observation"], snap["info"], snap["turn"])
        assert result1.state.psi["digest"] == result2.state.psi["digest"]

    def test_total_dof_index_finite(self, snapshots, extractor):
        """TotalDoF_index should be finite (not -inf or nan)."""
        for snap in snapshots:
            result = extractor.extract(snap["observation"], snap["info"], snap["turn"])
            index = compute_total_dof_index(result.state)
            assert math.isfinite(index)
            assert index < 0  # all entities have DoF < 1, so ln(DoF) < 0

    def test_units_extracted(self, snapshots, extractor):
        """At least one unit should be extracted (the player has units)."""
        for snap in snapshots:
            result = extractor.extract(snap["observation"], snap["info"], snap["turn"])
            units = [e for e in result.state.entities if e.startswith("unit_")]
            assert len(units) > 0, "No units extracted"

    def test_cities_extracted(self, snapshots, extractor):
        """At least one city should be extracted."""
        has_city = False
        for snap in snapshots:
            result = extractor.extract(snap["observation"], snap["info"], snap["turn"])
            cities = [e for e in result.state.entities if e.startswith("city_")]
            if cities:
                has_city = True
                break
        assert has_city, "No cities extracted from any snapshot"

    def test_entity_count_grows_over_turns(self, snapshots, extractor):
        """Entity count should generally grow (cities expand, units build)."""
        if len(snapshots) < 2:
            pytest.skip("Need at least 2 snapshots")
        early = extractor.extract(snapshots[0]["observation"], snapshots[0]["info"], snapshots[0]["turn"])
        late = extractor.extract(snapshots[-1]["observation"], snapshots[-1]["info"], snapshots[-1]["turn"])
        assert len(late.state.entities) >= len(early.state.entities)


@requires_observations
class TestObservationFormatDiscovery:
    """Tests to discover and document the real observation format."""

    def test_observation_keys(self):
        """Print all top-level keys in the observation dict."""
        snapshots = load_observations()
        if not snapshots:
            pytest.skip("No snapshots")
        obs = snapshots[0]["observation"]
        print(f"\nTop-level observation keys: {list(obs.keys())}")

    def test_unit_observation_structure(self):
        """Print structure of a single unit observation."""
        snapshots = load_observations()
        if not snapshots:
            pytest.skip("No snapshots")
        obs = snapshots[0]["observation"]
        units = obs.get("unit", {})
        if units:
            first_unit_id = next(iter(units))
            unit_data = units[first_unit_id]
            print(f"\nUnit {first_unit_id} observation keys: {list(unit_data.keys())}")

    def test_city_observation_structure(self):
        """Print structure of a single city observation."""
        snapshots = load_observations()
        if not snapshots:
            pytest.skip("No snapshots")
        obs = snapshots[0]["observation"]
        cities = obs.get("city", {})
        if cities:
            first_city_id = next(iter(cities))
            city_data = cities[first_city_id]
            print(f"\nCity {first_city_id} observation keys: {list(city_data.keys())}")
