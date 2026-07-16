"""Global Quality Index: the attempt table and its regeneration (globalqualityindex)."""
import csv

import pytest

pytestmark = pytest.mark.realdata


def test_gqi_table_has_expected_columns_and_regenerates(one_meg, isolated_dataset, full_config, cli):
    ds = isolated_dataset(one_meg[1])
    rc = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(full_config), "--n_jobs", "1"])
    assert rc.returncode == 0, rc.stdout[-3000:]
    root = ds / "derivatives" / "MEEGqc"

    # calculation already writes a GQI attempt table with a BIDS-valid name
    gqi = list(root.glob("summary_reports/**/desc-GlobalQualityIndexAttempt*_*.tsv"))
    assert gqi, "no GQI attempt table after calculation"
    with open(gqi[0], encoding="utf-8") as f:
        header = next(csv.reader(f, delimiter="\t"))
    assert "task" in header, f"GQI table missing 'task' column: {header}"
    assert any("GQI" in h for h in header), f"GQI table missing a GQI score column: {header}"

    # regenerate the GQI independently (a second attempt)
    r = cli(["globalqualityindex", "--inputdata", str(ds)])
    assert r.returncode == 0, r.stdout[-3000:]
