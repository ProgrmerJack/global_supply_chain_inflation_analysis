"""Timestamp parsing for bulk reads of the parquet ping store.

HISTORY (2026-08-05) -- read before editing. NOAA changed the `BaseDateTime` encoding partway
through 2023, from ISO ("2023-01-02T00:00:58") to space-separated ("2023-05-03 00:01:11").
pandas >= 2 infers ONE datetime format from the first element of the column and coerces
everything that does not match it. Scripts that read the store a WHOLE YEAR AT A TIME therefore
hit a silent cliff in 2023 -- the only year that straddles the change:

    2023 LA/LB rows       6,394,597
      ISO (Jan-Feb)       1,224,077   parsed
      space-sep (May-Dec) 5,170,520   coerced to NaT and dropped  (80.9% of the year)

Every other year is uniform (2015-2022 ISO, 2024-2025 space-separated) and so parsed cleanly,
which is why the loss looked like nothing at all. The production census builders (`mode_time.py`,
`compute_dwell_metrics.py`, `extract_port_observations.py`) were never affected because they
process one source file at a time and each file is internally consistent -- the monthly census
contains normal values for 2023-05..2023-12.

Two guards were affected and reported wrong 2023 figures: `ais_qc.py` (anomaly rates on a
5x-too-small denominator) and `port_call_segmentation.py` (639 port calls in 2023 against
~4,000 in neighbouring years). `dwell_segmentation_sensitivity.py` shares the same read shape.

The fix is `format="mixed"`, which parses each element on its own terms. The loss check below is
the part that actually matters: a silent drop must never again pass as a successful read.
"""

from __future__ import annotations

import pandas as pd

# A real store has a negligible number of unparseable timestamps. Anything above this is a
# format problem, not dirty data, and must stop the run rather than shrink the sample.
MAX_UNPARSED_SHARE = 0.001


def parse_ping_time(raw: pd.Series, context: str, max_unparsed: float = MAX_UNPARSED_SHARE) -> pd.Series:
    """Parse a `BaseDateTime` column, tolerating mixed encodings, and refuse to lose rows.

    `context` names the slice being read (e.g. "port_pings 2023") so a failure says where.
    """
    if not len(raw):
        return pd.to_datetime(raw, errors="coerce")

    already_null = int(raw.isna().sum())
    parsed = pd.to_datetime(raw, errors="coerce", format="mixed")
    lost = int(parsed.isna().sum()) - already_null
    share = lost / len(raw)

    if share > max_unparsed:
        sample = raw[parsed.isna() & raw.notna()].astype(str).head(3).tolist()
        raise ValueError(
            f"{context}: {lost:,} of {len(raw):,} timestamps ({share:.1%}) failed to parse — "
            f"far above the {max_unparsed:.1%} tolerance. Unparsed examples: {sample}. "
            "Do not proceed: this is a source-format change, and dropping the rows would "
            "silently shrink the sample (see the HISTORY note in this module)."
        )
    return parsed
