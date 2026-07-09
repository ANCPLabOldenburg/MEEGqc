"""Analysis modes (profile / non-profile + aliases) and skip/rerun semantics."""
import pytest

pytestmark = pytest.mark.realdata


def _calc(ds):
    return ds / "derivatives" / "MEEGqc" / "calculation"


def test_non_profile_writes_flat(one_meg, isolated_dataset, fast_config, cli):
    ds = isolated_dataset(one_meg[1])
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
             "--n_jobs", "1", "--analysis_mode", "non-profile"])
    assert r.returncode == 0, r.stdout[-3000:]
    assert _calc(ds).is_dir()
    assert not (ds / "derivatives" / "MEEGqc" / "profiles").exists()


def test_new_profile_and_latest(one_meg, isolated_dataset, fast_config, cli):
    ds = isolated_dataset(one_meg[1])
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
             "--n_jobs", "1", "--analysis_mode", "new-profile", "--analysis_id", "p1"])
    assert r.returncode == 0, r.stdout[-3000:]
    prof = ds / "derivatives" / "MEEGqc" / "profiles" / "p1" / "calculation"
    assert prof.is_dir(), "new-profile did not create profiles/p1/calculation"


def test_legacy_alias_maps_to_non_profile(one_meg, isolated_dataset, fast_config, cli):
    """The old 'legacy' name still works and behaves like non-profile."""
    ds = isolated_dataset(one_meg[1])
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
             "--n_jobs", "1", "--analysis_mode", "legacy"])
    assert r.returncode == 0, r.stdout[-3000:]
    assert _calc(ds).is_dir()
    assert not (ds / "derivatives" / "MEEGqc" / "profiles").exists()


def test_bogus_mode_rejected(one_meg, isolated_dataset, fast_config, cli):
    ds = isolated_dataset(one_meg[1])
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config),
             "--analysis_mode", "definitely-not-a-mode"])
    assert r.returncode != 0
    assert "invalid choice" in (r.stdout + r.stderr).lower()


def test_skip_then_rerun(one_meg, isolated_dataset, fast_config, cli):
    """skip skips already-processed subjects; rerun overwrites without crashing."""
    ds = isolated_dataset(one_meg[1])
    base = ["run-meegqc", "--inputdata", str(ds), "--config", str(fast_config), "--n_jobs", "1"]

    r1 = cli(base)
    assert r1.returncode == 0
    subs = {p.name for p in _calc(ds).glob("*/sub-*")}
    assert subs, "first run produced no subjects"

    # default re-run (skip): must NOT crash and must NOT reprocess
    r2 = cli(base)
    assert r2.returncode == 0
    assert "FileExistsError" not in (r2.stdout + r2.stderr)
    assert "already processed" in (r2.stdout + r2.stderr).lower()

    # explicit rerun: reprocesses, overwrites cleanly, no FileExistsError
    r3 = cli(base + ["--processed_subjects_policy", "rerun"])
    assert r3.returncode == 0
    assert "FileExistsError" not in (r3.stdout + r3.stderr)
