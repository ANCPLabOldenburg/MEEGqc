"""Calculation runs on every dataset in the bundle and writes BIDS-valid names."""
import re

import pytest

pytestmark = pytest.mark.realdata


def _desc_labels(paths):
    for f in paths:
        m = re.search(r"_desc-([^_]+)_", f.name)
        if m:
            yield f.name, m.group(1)


def test_calculation_all_datasets(any_dataset, isolated_dataset, fast_config, cli):
    """Every dataset (all formats) loads, processes, and writes derivatives."""
    name, path = any_dataset
    ds = isolated_dataset(path)
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
             "--n_jobs", "1"])
    assert r.returncode == 0, (r.stdout[-4000:] + "\n--STDERR--\n" + r.stderr[-2000:])

    calc = ds / "derivatives" / "MEEGqc" / "calculation"
    assert calc.is_dir(), f"{name}: no calculation folder written"

    stds = list(calc.glob("*/sub-*/*_desc-STDs_*.tsv"))
    assert stds, f"{name}: no desc-STDs derivative"

    # every derivative desc label must be BIDS-valid (alphanumeric, no underscores)
    bad = [fn for fn, label in _desc_labels(calc.glob("*/sub-*/*_desc-*.*"))
           if not re.fullmatch(r"[A-Za-z0-9]+", label)]
    assert not bad, f"{name}: non-BIDS desc labels: {bad[:5]}"


def test_no_crash_and_no_fileexists(any_dataset, isolated_dataset, fast_config, cli):
    """A fresh calc never raises the FileExistsError regression (issue #137)."""
    name, path = any_dataset
    ds = isolated_dataset(path)
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
             "--n_jobs", "1"])
    assert r.returncode == 0
    assert "FileExistsError" not in (r.stdout + r.stderr), f"{name}: FileExistsError"
