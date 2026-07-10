"""Analysis modes (non-profile / profile) and skip/rerun semantics."""
import pytest

pytestmark = pytest.mark.realdata

BASE = ["run-meegqc", "--n_jobs", "1"]


def _calc(ds):
    return ds / "derivatives" / "MEEGqc" / "calculation"


def _profiles(ds):
    return ds / "derivatives" / "MEEGqc" / "profiles"


def test_non_profile_writes_under_meegqc_without_profiles(one_meg, isolated_dataset, fast_config, cli):
    ds = isolated_dataset(one_meg[1])
    r = cli([*BASE, "--inputdata", str(ds), "--config", str(fast_config),
             "--analysis_mode", "non-profile"])
    assert r.returncode == 0, r.stdout[-3000:]
    assert _calc(ds).is_dir()
    assert not _profiles(ds).exists()


def test_new_profile_creates_profiles_subfolder(one_meg, isolated_dataset, fast_config, cli):
    ds = isolated_dataset(one_meg[1])
    r = cli([*BASE, "--inputdata", str(ds), "--config", str(fast_config),
             "--analysis_mode", "new-profile", "--analysis_id", "p1"])
    assert r.returncode == 0, r.stdout[-3000:]
    assert (_profiles(ds) / "p1" / "calculation").is_dir()


def test_latest_profile_resolves_newest_profile(one_meg, isolated_dataset, fast_config, cli):
    """latest-profile targets the most recently created profile (here 'p1')."""
    ds = isolated_dataset(one_meg[1])
    r1 = cli([*BASE, "--inputdata", str(ds), "--config", str(fast_config),
              "--analysis_mode", "new-profile", "--analysis_id", "p1"])
    assert r1.returncode == 0, r1.stdout[-3000:]
    r2 = cli(["run-meegqc-plotting", "--inputdata", str(ds), "--qa-subject",
              "--analysis_mode", "latest-profile"])
    assert r2.returncode == 0, r2.stdout[-3000:]
    assert list((_profiles(ds) / "p1" / "reports").glob("*/sub-*/*subjectQaReport*.html")), \
        "latest-profile did not render into the newest profile 'p1'"


def test_unknown_analysis_mode_is_rejected(one_meg, isolated_dataset, fast_config, cli):
    ds = isolated_dataset(one_meg[1])
    r = cli([*BASE, "--inputdata", str(ds), "--config", str(fast_config),
             "--analysis_mode", "definitely-not-a-mode"])
    assert r.returncode != 0
    assert "invalid choice" in (r.stdout + r.stderr).lower()


def test_skip_skips_processed_subjects_and_rerun_overwrites(one_meg, isolated_dataset, fast_config, cli):
    """Default 'skip' skips already-processed subjects; 'rerun' overwrites, no crash."""
    ds = isolated_dataset(one_meg[1])
    run = [*BASE, "--inputdata", str(ds), "--config", str(fast_config)]

    r1 = cli(run)
    assert r1.returncode == 0
    assert {p.name for p in _calc(ds).glob("*/sub-*")}, "first run produced no subjects"

    # default re-run (skip): must NOT crash and must NOT reprocess
    r2 = cli(run)
    assert r2.returncode == 0
    assert "FileExistsError" not in (r2.stdout + r2.stderr)
    assert "already processed" in (r2.stdout + r2.stderr).lower()

    # explicit rerun: reprocesses, overwrites cleanly, no FileExistsError
    r3 = cli(run + ["--processed_subjects_policy", "rerun"])
    assert r3.returncode == 0
    assert "FileExistsError" not in (r3.stdout + r3.stderr)
