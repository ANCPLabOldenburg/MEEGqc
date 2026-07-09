"""The programmatic dispatchers behave like the CLI (calculation + plotting)."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.realdata


def _internal_cfg() -> str:
    import meg_qc
    return str(Path(meg_qc.__file__).parent / "settings" / "settings_internal.ini")


def test_run_calculation_and_plotting_dispatch(one_meg, isolated_dataset, fast_config):
    from meg_qc.test import run_calculation_dispatch, run_plotting_dispatch

    ds = isolated_dataset(one_meg[1])
    run_calculation_dispatch(
        dataset_paths=[str(ds)],
        config_file_path=str(fast_config),
        internal_config_file_path=_internal_cfg(),
        sub_list="all",
        n_jobs=1,
        analysis_mode="non-profile",
    )
    calc = ds / "derivatives" / "MEEGqc" / "calculation"
    assert calc.is_dir()
    assert list(calc.glob("*/sub-*/*_desc-STDs_*.tsv"))

    run_plotting_dispatch(dataset_paths=[str(ds)], qa_subject=True,
                          analysis_mode="non-profile")
    assert list((ds / "derivatives" / "MEEGqc" / "reports").glob("*/sub-*/*subjectQaReport*.html"))


def test_normalize_analysis_mode_aliases():
    from meg_qc.calculation.meg_qc_pipeline import normalize_analysis_mode as n
    assert n("legacy") == "non-profile"
    assert n("new") == "new-profile"
    assert n("reuse") == "reuse-profile"
    assert n("latest") == "latest-profile"
    assert n(None) == "non-profile"
    assert n("NEW-PROFILE") == "new-profile"
