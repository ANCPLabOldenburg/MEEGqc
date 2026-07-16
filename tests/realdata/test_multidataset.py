"""Multi-dataset QA / QC reports across two datasets."""
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.realdata


def test_multi_dataset_qa_qc(two_datasets, tmp_path, fast_config, cli):
    paths = []
    for name, path in two_datasets:
        dst = tmp_path / name
        shutil.copytree(path, dst)
        paths.append(str(dst))

    r = cli(["run-meegqc", "--inputdata", *paths, "--config", str(fast_config), "--n_jobs", "1"])
    assert r.returncode == 0, r.stdout[-3000:]

    r2 = cli(["run-meegqc-plotting", "--inputdata", *paths,
              "--qa-multi-dataset", "--qc-multi-dataset"])
    assert r2.returncode == 0, r2.stdout[-3000:]

    # multi-dataset reports land under the first dataset's reports folder
    reports = list(Path(paths[0]).glob("derivatives/MEEGqc/reports/**/*multiDataset*.html"))
    assert reports, "no multi-dataset report written"
