"""End-to-end coverage for literal external output."""

import shutil

import pytest

pytestmark = pytest.mark.realdata


@pytest.mark.parametrize("analysis_mode", ["non-profile", "new-profile"])
def test_literal_output_calculation_and_plotting(
    one_meg,
    isolated_dataset,
    fast_config,
    cli,
    tmp_path,
    analysis_mode,
):
    dataset = isolated_dataset(one_meg[1])
    output = tmp_path / "quality-control"
    common = [
        "--inputdata",
        str(dataset),
        "--derivatives_output",
        str(output),
        "--output_layout",
        "literal",
        "--analysis_mode",
        analysis_mode,
    ]
    root = output / "MEEGqc"
    if analysis_mode == "new-profile":
        common += ["--analysis_id", "literal-test"]
        root = root / "profiles" / "literal-test"

    calculation = cli(
        ["run-meegqc", *common, "--config", str(fast_config), "--n_jobs", "1"]
    )
    assert calculation.returncode == 0, (calculation.stdout + calculation.stderr)[-3000:]

    calculation_root = root / "calculation"
    assert calculation_root.is_dir()
    assert list(calculation_root.rglob("*_desc-STDs_*.tsv"))
    assert not (output / dataset.name).exists()
    assert not (output / "derivatives").exists()
    assert not (dataset / "derivatives").exists()

    plotting = cli(["run-meegqc-plotting", *common, "--qa-subject"])
    assert plotting.returncode == 0, (plotting.stdout + plotting.stderr)[-3000:]
    reports = root / "reports"
    assert list(reports.glob("*/sub-*/*subjectQaReport*.html"))


def test_literal_multi_dataset_profile_reports(one_meg, fast_config, cli, tmp_path):
    datasets = [tmp_path / "dataset-a", tmp_path / "dataset-b"]
    for dataset in datasets:
        shutil.copytree(one_meg[1], dataset)
    output = tmp_path / "quality-control"
    common = [
        "--inputdata", *map(str, datasets),
        "--derivatives_output", str(output),
        "--output_layout", "literal",
        "--analysis_mode", "new-profile",
        "--analysis_id", "literal-multi",
    ]
    calculation = cli(
        ["run-meegqc", *common, "--config", str(fast_config), "--n_jobs", "1"]
    )
    assert calculation.returncode == 0, (calculation.stdout + calculation.stderr)[-3000:]
    roots = [
        output / dataset.name / "MEEGqc" / "profiles" / "literal-multi"
        for dataset in datasets
    ]
    for dataset, root in zip(datasets, roots):
        assert list((root / "calculation").rglob("*_desc-STDs_*.tsv"))
        assert not (output / dataset.name / "derivatives").exists()
        assert not (dataset / "derivatives").exists()

    plotting = cli([
        "run-meegqc-plotting", *common, "--qa-subject", "--qa-multi-dataset",
    ])
    assert plotting.returncode == 0, (plotting.stdout + plotting.stderr)[-3000:]
    for root in roots:
        assert list((root / "reports").glob("*/sub-*/*subjectQaReport*.html"))
    assert list((roots[0] / "reports").rglob("*multiDataset*.html"))
