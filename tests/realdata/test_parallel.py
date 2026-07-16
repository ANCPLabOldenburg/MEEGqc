"""Multi-core (joblib / loky) execution.

These run with n_jobs > 1 so the joblib parallel backend is exercised on every
Python version and platform in the CI matrix. Parallel worker startup (loky /
spawn) is a common source of version- and OS-specific breakage, so it is worth
a dedicated check separate from the serial tests.
"""
import pytest

pytestmark = pytest.mark.realdata


def _subjects(ds):
    calc = ds / "derivatives" / "MEEGqc" / "calculation"
    return {p.name for p in calc.glob("*/sub-*")}


def test_parallel_calculation_two_jobs(two_subject_dataset, isolated_dataset, fast_config, cli):
    """n_jobs=2 processes several subjects in parallel without crashing."""
    name, path = two_subject_dataset
    ds = isolated_dataset(path)
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
             "--n_jobs", "2"])
    assert r.returncode == 0, (r.stdout[-4000:] + "\n--STDERR--\n" + r.stderr[-2000:])
    # joblib/loky must not fall over on this Python/OS
    joined = r.stdout + r.stderr
    for marker in ("FileExistsError", "BrokenProcessPool", "TerminatedWorkerError",
                   "cannot pickle", "A worker process managed by the executor was "
                   "unexpectedly terminated"):
        assert marker not in joined, f"{name}: parallel run reported '{marker}'"
    subs = _subjects(ds)
    assert len(subs) >= 2, f"{name}: expected >= 2 subjects processed, got {sorted(subs)}"


def test_parallel_plotting_njobs(two_subject_dataset, isolated_dataset, fast_config, cli):
    """Plotting with --njobs 2 (note: no underscore) also runs multi-core."""
    name, path = two_subject_dataset
    ds = isolated_dataset(path)
    rc = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
              "--n_jobs", "2"])
    assert rc.returncode == 0, rc.stdout[-3000:]
    rp = cli(["run-meegqc-plotting", "--inputdata", str(ds), "--qa-subject", "--njobs", "2"])
    assert rp.returncode == 0, (rp.stdout[-4000:] + "\n--STDERR--\n" + rp.stderr[-2000:])
    reports = list((ds / "derivatives" / "MEEGqc" / "reports").glob("*/sub-*/*subjectQaReport*.html"))
    assert len(reports) >= 2, f"{name}: expected a subject report per subject"
