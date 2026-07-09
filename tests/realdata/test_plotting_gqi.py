"""Report rendering (subject / dataset QA + QC) and GQI regeneration."""
import pytest

pytestmark = pytest.mark.realdata


def _calc(cli, ds, cfg):
    r = cli(["run-meegqc", "--inputdata", str(ds), "--config", str(cfg), "--n_jobs", "1"])
    assert r.returncode == 0, r.stdout[-3000:]
    return ds / "derivatives" / "MEEGqc"


def test_subject_and_dataset_qa_reports(one_meg, isolated_dataset, full_config, cli):
    ds = isolated_dataset(one_meg[1])
    root = _calc(cli, ds, full_config)
    r = cli(["run-meegqc-plotting", "--inputdata", str(ds), "--qa-subject", "--qa-dataset"])
    assert r.returncode == 0, r.stdout[-3000:]
    reports = root / "reports"
    subj = list(reports.glob("*/sub-*/*subjectQaReport*.html"))
    assert subj, "no subject QA report"
    assert all(h.stat().st_size > 1000 for h in subj)
    assert list(reports.glob("*/*datasetQaReport*.html")), "no dataset QA report"


def test_qc_dataset_report(one_meg, isolated_dataset, full_config, cli):
    ds = isolated_dataset(one_meg[1])
    root = _calc(cli, ds, full_config)
    r = cli(["run-meegqc-plotting", "--inputdata", str(ds), "--qc-dataset"])
    assert r.returncode == 0, r.stdout[-3000:]
    assert list((root / "reports").glob("*/*datasetQcReport*.html")), "no dataset QC report"


def test_gqi_tables_and_regeneration(one_meg, isolated_dataset, full_config, cli):
    ds = isolated_dataset(one_meg[1])
    root = _calc(cli, ds, full_config)
    # calc already writes a GQI attempt table with a BIDS-valid name
    gqi = list(root.glob("summary_reports/**/desc-GlobalQualityIndexAttempt*_*.tsv"))
    assert gqi, "no GQI attempt table after calculation"
    # regenerate GQI independently
    r = cli(["globalqualityindex", "--inputdata", str(ds)])
    assert r.returncode == 0, r.stdout[-3000:]


def test_eeg_reports(one_eeg, isolated_dataset, full_config, cli):
    ds = isolated_dataset(one_eeg[1])
    root = _calc(cli, ds, full_config)
    r = cli(["run-meegqc-plotting", "--inputdata", str(ds), "--qa-subject"])
    assert r.returncode == 0, r.stdout[-3000:]
    assert list((root / "reports").glob("eeg/sub-*/*subjectQaReport*.html")), \
        "no EEG subject QA report"
