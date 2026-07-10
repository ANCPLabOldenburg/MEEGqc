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
    # Derivatives may be nested under a ses-<label> level (issue #132), so the
    # search must be recursive rather than glob at a fixed sub-XXX/ depth.
    std_derivs = list(calc.rglob("*_desc-STDs_*.tsv"))
    assert std_derivs, f"{name}: no desc-STDs derivative"

    # #132: the derivative tree must mirror the raw BIDS sub-XXX/ses-YYY/ layout.
    # Any derivative whose filename carries a session entity must live inside a
    # ses-<label> folder (and no derivative should sit in a bare ses- folder
    # without the matching filename entity). This exercises both the nested and
    # the flat (non-session) layouts without needing to know the dataset upfront.
    for f in calc.rglob("*_desc-*.*"):
        m_ses = re.search(r"_ses-([A-Za-z0-9]+)_", f.name)
        parent = f.parent.name
        if m_ses:
            assert parent == f"ses-{m_ses.group(1)}", (
                f"{name}: {f.name} carries ses-{m_ses.group(1)} but is not nested "
                f"under that session folder (parent={parent})")
        else:
            assert not parent.startswith("ses-"), (
                f"{name}: {f.name} has no session entity but sits in {parent}")

    # every derivative desc label must be BIDS-valid (alphanumeric, no underscores)
    bad = []
    for f in calc.rglob("*_desc-*.*"):
        m = re.search(r"_desc-([^_]+)_", f.name)
        if m and not re.fullmatch(r"[A-Za-z0-9]+", m.group(1)):
            bad.append(f.name)
    assert not bad, f"{name}: non-BIDS desc labels: {bad[:5]}"
