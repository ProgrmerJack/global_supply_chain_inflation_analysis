"""Blind vessel-state validation mapping + decomposed scoring (blind_state_validation.py).

Navigation status is treated as a NOISY AUXILIARY reference. The primary metric is 2-class motion; the
berth-vs-anchor split is auxiliary with an explicit unknown_stationary class. Mocked classifier; no download.
"""

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)


def test_every_classifier_state_maps_to_motion():
    from process_ais.blind_state_validation import STATE_TO_MOTION
    from process_ais.mode_time import STATE_NAMES

    unmapped = set(STATE_NAMES) - set(STATE_TO_MOTION)
    assert not unmapped, f"classifier states with no motion mapping (would silently drop pings): {unmapped}"
    assert set(STATE_TO_MOTION.values()) <= {"moving", "stationary"}


def test_uncharted_wait_is_unknown_stationary_not_forced():
    from process_ais.blind_state_validation import STATE_TO_BERTH

    # a stationary vessel outside charted berth/anchorage must NOT be forced into anchored/moored
    assert STATE_TO_BERTH["uncharted_near_port_wait"] == "unknown_stationary"
    assert STATE_TO_BERTH["berth"] == "moored"
    assert STATE_TO_BERTH["official_anchorage"] == "anchored"


def test_status_maps():
    from process_ais.blind_state_validation import STATUS_TO_MOTION, STATUS_TO_BERTH

    assert STATUS_TO_MOTION[0] == "moving" and STATUS_TO_MOTION[1] == "stationary" and STATUS_TO_MOTION[5] == "stationary"
    assert STATUS_TO_BERTH[1] == "anchored" and STATUS_TO_BERTH[5] == "moored"


def test_status_sample_reads_the_retained_static_sample_without_a_download(tmp_path):
    """The completed static sample supplies G1 labels locally and caps each port-day deterministically."""
    from process_ais.blind_state_validation import status_sample_from_retained

    sample_dir = tmp_path / "vessel_static_sample" / "year=2021" / "month=01"
    sample_dir.mkdir(parents=True)
    pings = pd.DataFrame(
        {
            "mmsi": [100, 101, 102, 200, 201],
            "timestamp": pd.to_datetime(
                [
                    "2021-01-15T00:00:00Z", "2021-01-15T01:00:00Z", "2021-01-15T02:00:00Z",
                    "2021-01-15T00:00:00Z", "2021-01-15T01:00:00Z",
                ],
                utc=True,
            ),
            "port_complex_id": ["alpha", "alpha", "alpha", "bravo", "bravo"],
            "lat": [0.0] * 5,
            "lon": [0.0] * 5,
            "sog": [0.0, 0.1, 0.2, 8.0, 9.0],
            "vessel_type": [70, 70, 70, 70, 70],
            "status": pd.Series([5, 1, 0, 0, 8], dtype="Int64"),
        }
    )
    pings.to_parquet(sample_dir / "pings_2021-01-15.parquet", index=False)

    sample = status_sample_from_retained(tmp_path / "vessel_static_sample", max_pings_per_port_day=1)

    assert sample.columns.tolist() == ["mmsi", "port_complex_id", "lat", "lon", "sog", "nav_status"]
    assert len(sample) == 2
    assert set(sample.port_complex_id) == {"alpha", "bravo"}


def test_decomposed_scoring_wiring(monkeypatch):
    import process_ais.blind_state_validation as bsv

    sample = pd.DataFrame({
        "mmsi": [1, 2, 3, 4, 5],
        "port_complex_id": ["p"] * 5,
        "lat": [0.0] * 5, "lon": [0.0] * 5, "sog": [0.0, 0.0, 10.0, 0.0, 10.0],
        "nav_status": [5, 1, 0, 5, 0],   # moored, anchored, moving, moored, moving
    })

    def fake_assign(df, zones, *, zone_priority):
        # berth, anchorage, transit, uncharted(unknown), transit
        return df.assign(state=["berth", "official_anchorage", "transit", "uncharted_near_port_wait", "transit"])

    monkeypatch.setattr(bsv, "assign_state_labels", fake_assign)
    metrics, labels = bsv.macro_f1_from_sample(sample, zones=None)
    # motion: truth=[stat,stat,mov,stat,mov], pred=[stat,stat,mov,stat,mov] -> perfect
    assert metrics["motion_macro_f1"] == pytest.approx(1.0)
    # the 4th ping (moored truth) is classified unknown_stationary -> counted as unresolved, not an error
    assert metrics["berth_unresolved_stationary_share"] > 0
    assert "moving" in metrics["motion_per_class"] and "stationary" in metrics["motion_per_class"]
    assert len(labels) == 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
