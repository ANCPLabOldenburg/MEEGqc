"""Recording-level derivative writes respect the selected output layout."""

from pathlib import Path

import ancpbids
import pandas as pd
import pytest

from meg_qc.calculation.meg_qc_pipeline import _register_and_write
from meg_qc.calculation.objects import QC_derivative


@pytest.mark.parametrize("output_layout", ["bids", "literal"])
@pytest.mark.parametrize("analysis_segments", [[], ["profiles", "layout-test"]])
def test_recording_derivative_output_layout(tmp_path, output_layout, analysis_segments):
    source = tmp_path / "dataset"
    raw_dir = source / "sub-01" / "meg"
    raw_dir.mkdir(parents=True)
    (source / "dataset_description.json").write_text(
        '{"Name": "source", "BIDSVersion": "1.8.0"}', encoding="utf-8"
    )
    (raw_dir / "sub-01_task-rest_run-01_meg.fif").touch()
    dataset = ancpbids.load_dataset(str(source))
    entities = dataset.query(suffix="meg", extension=".fif", scope="raw")
    values = pd.DataFrame({"STD": [1.0, 2.0]})
    result = {
        "file_ind": 0,
        "meg_system": "MEG",
        "QC_derivs": {"STD": [QC_derivative(values, "STDs", "df")]},
    }
    output = tmp_path / "output"
    if output_layout == "bids":
        output = output / source.name
    original_name = dataset.name

    count = _register_and_write(
        result,
        dataset=dataset,
        sub="01",
        entities_per_file=entities,
        analysis_segments=analysis_segments,
        output_root=str(output),
        output_layout=output_layout,
    )

    root = output / "derivatives" if output_layout == "bids" else output
    target = (
        root / "MEEGqc" / Path(*analysis_segments) / "calculation" / "meg" / "sub-01"
        / "sub-01_task-rest_run-01_desc-STDs_meg.tsv"
    )
    assert count == 1
    pd.testing.assert_frame_equal(pd.read_csv(target, sep="\t"), values)
    assert not (source / "derivatives").exists()
    if output_layout == "literal":
        assert not (output / "derivatives").exists()
    assert Path(dataset.base_dir_) == source
    assert dataset.name == original_name
    assert not any(folder.name == "MEEGqc" for folder in dataset.derivatives.folders)
