"""Output completeness: a full-metric run writes EVERY expected file.

The missing-GQI bug (session-nested datasets produced no group table) shipped
green because every prior test ran on flat datasets and only checked a subset of
outputs. These tests run the full metric set on two representative bundle
datasets and assert the WHOLE per-metric derivative set plus a complete GQI group
table is written, for a flat dataset and a session-nested one:

  ds_camcan - flat MEG
  ds_1      - session (ses-1) MEG

Head movement is intentionally NOT validated here: it needs the full continuous
signal, but the bundle ships 10 s crops, so it is never produced on the fixtures.

A dataset absent from the bundle skips (see the ``named_dataset`` fixture).
"""
import csv

import pytest

pytestmark = pytest.mark.realdata

# Signature per-recording derivative each metric writes: desc-<name>_<mod>.tsv.
_METRIC_DERIV = {
    "STD": "STDs",
    "PSD": "PSDs",
    "PtP": "PtPsManual",
    "ECG": "ECGs",
    "EOG": "EOGs",
    "Muscle": "Muscle",
}

# (dataset name in the bundle, metrics whose files MUST be produced).
_CASES = [
    ("ds_camcan", {"STD", "PSD", "PtP", "ECG", "EOG", "Muscle"}),
    ("ds_1", {"STD", "PSD", "PtP", "ECG", "EOG", "Muscle"}),
]


@pytest.mark.parametrize("ds_name,expected", _CASES, ids=[c[0] for c in _CASES])
def test_full_output_produced(
    ds_name, expected, named_dataset, isolated_dataset, full_config, cli
):
    """Run the common metrics and assert every expected output file exists.

    ``rglob`` is used throughout so session-nested derivatives
    (calculation/<mod>/sub-XXX/ses-YYY/..., issue #132) are matched too."""
    path = named_dataset(ds_name)
    ds = isolated_dataset(path)
    rc = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(full_config), "--n_jobs", "1"])
    assert rc.returncode == 0, rc.stdout[-4000:]

    calc = ds / "derivatives" / "MEEGqc" / "calculation"
    assert calc.is_dir(), f"{ds_name}: no calculation folder"

    # every expected metric wrote its signature derivative
    missing = [m for m in sorted(expected)
               if not list(calc.rglob(f"*_desc-{_METRIC_DERIV[m]}_*.tsv"))]
    assert not missing, f"{ds_name}: metrics with no derivative file: {missing}"

    # a SimpleMetrics JSON per recording, and a COMPLETE GQI group table
    recordings = list(calc.rglob("*SimpleMetrics_*.json"))
    assert recordings, f"{ds_name}: no SimpleMetrics produced"
    root = ds / "derivatives" / "MEEGqc"
    gqi = list(root.glob("summary_reports/group_metrics/**/desc-GlobalQualityIndexAttempt*_*.tsv"))
    assert gqi, f"{ds_name}: GQI group table missing (session-nesting regression?)"

    rows = []
    for tsv in gqi:
        with open(tsv, encoding="utf-8") as f:
            rows.extend(csv.DictReader(f, delimiter="\t"))
    assert len(rows) == len(recordings), (
        f"{ds_name}: GQI has {len(rows)} rows for {len(recordings)} recordings")

    # rows are labelled by the real subject, never the ses-YYY parent folder
    subjects = {str(r.get("subject", "")) for r in rows}
    assert subjects and all(s.startswith("sub-") for s in subjects), (
        f"{ds_name}: GQI subject labels are not sub-XXX: {sorted(subjects)}")

    # a session-nested recording must carry its ses label in the table
    if any("_ses-" in r.name for r in recordings):
        assert any(str(r.get("session", "")).strip() for r in rows), (
            f"{ds_name}: session dataset but no session recorded in the GQI table")
