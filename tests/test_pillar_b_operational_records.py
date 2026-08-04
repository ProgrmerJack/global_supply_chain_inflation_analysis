import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "process_ais"))


def _packet():
    return pd.DataFrame({
        "episode_id": ["call|123456789|e1", "call|987654321|e2"],
        "vessel_id_hash": ["a", "b"],
        "start_utc": ["2021-01-01T02:00:00Z", "2021-02-03T04:00:00Z"],
        "end_utc": ["2021-01-01T05:00:00Z", "2021-02-03T09:00:00Z"],
        "regime": ["hidden", "hidden"],
        "classifier_label": ["anchor", "berth"],
    })


def test_holder_packet_has_only_linkage_and_requested_record_fields():
    from pillar_b_operational_records import REQUEST_COLUMNS, request_rows

    request, mapping = request_rows(_packet())
    assert list(request.columns) == list(REQUEST_COLUMNS)
    assert request["mmsi"].tolist() == ["123456789", "987654321"]
    assert request.loc[0, "window_start_utc"] == "2020-12-31T02:00:00Z"
    assert request.loc[0, "window_end_utc"] == "2021-01-02T05:00:00Z"
    assert {"classifier_label", "regime", "episode_id", "vessel_id_hash"}.isdisjoint(request.columns)
    assert mapping["episode_id"].tolist() == _packet()["episode_id"].tolist()


def test_bad_episode_identifier_fails_closed():
    from pillar_b_operational_records import request_rows

    packet = _packet()
    packet.loc[0, "episode_id"] = "not-an-mmsi"
    with pytest.raises(ValueError, match="MMSI"):
        request_rows(packet)


def test_instantaneous_episode_gets_the_frozen_broad_request_window():
    from pillar_b_operational_records import request_rows

    packet = _packet().iloc[[0]].copy()
    packet.loc[packet.index[0], "end_utc"] = packet.loc[packet.index[0], "start_utc"]
    request, _ = request_rows(packet)
    assert request.loc[packet.index[0], "window_start_utc"] == "2020-12-31T02:00:00Z"
    assert request.loc[packet.index[0], "window_end_utc"] == "2021-01-02T02:00:00Z"


def test_osf_html_escaping_is_normalized_before_freeze_comparison():
    from pillar_b_operational_records import _unescape_response

    assert _unescape_response({"threshold": "F1 &gt;= 0.85", "nested": ["&lt;10%"]}) == {
        "threshold": "F1 >= 0.85", "nested": ["<10%"]
    }
