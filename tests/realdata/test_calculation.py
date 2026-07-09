"""Calculation runs on every dataset in the bundle and writes BIDS-valid names."""
import re

import pytest

pytestmark = pytest.mark.realdata


def test_calculation_writes_bids_valid_derivatives(any_dataset, isolated_dataset, fast_config, cli):
    """Every dataset (all formats) loads, processes, writes derivatives with
    BIDS-valid desc labels, and does not hit the FileExistsError regression (#137)."""
    name, path = any_dataset
    ds = isolated_dataset(path)
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config), "--n_jobs", "1"])
    assert r.returncode == 0, (r.stdout[-4000:] + "\n--STDERR--\n" + r.stderr[-2000:])
    assert "FileExistsError" not in (r.stdout + r.stderr), f"{name}: FileExistsError on a fresh run"

    calc = ds / "derivatives" / "MEEGqc" / "calculation"
    assert calc.is_dir(), f"{name}: no calculation folder written"
    assert list(calc.glob("*/sub-*/*_desc-STDs_*.tsv")), f"{name}: no desc-STDs derivative"

    # every derivative desc label must be BIDS-valid (alphanumeric, no underscores)
    bad = []
    for f in calc.glob("*/sub-*/*_desc-*.*"):
        m = re.search(r"_desc-([^_]+)_", f.name)
        if m and not re.fullmatch(r"[A-Za-z0-9]+", m.group(1)):
            bad.append(f.name)
    assert not bad, f"{name}: non-BIDS desc labels: {bad[:5]}"
