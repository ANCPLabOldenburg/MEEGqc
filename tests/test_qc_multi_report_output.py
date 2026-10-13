"""Multi-dataset QC reports use the selected output location."""

import pandas as pd
import pytest

from meg_qc.plotting.meg_qc_dataset_qc_plots import make_dataset_qc_plots_multi_meg_qc


@pytest.mark.parametrize("explicit_output", [False, True], ids=["default", "explicit"])
def test_multi_dataset_qc_report_output_paths(tmp_path, explicit_output):
    datasets = []
    for modality in ("meg", "eeg"):
        dataset = tmp_path / f"dataset-{modality}"
        metrics = (
            dataset / "derivatives" / "MEEGqc" / "summary_reports"
            / "group_metrics" / modality
        )
        metrics.mkdir(parents=True)
        row = {"subject": "sub-01", "task": "rest", "GQI": 90.0}
        for metric in ("STD", "PTP"):
            for channel_type in ("mag", "grad", "eeg"):
                row[f"{metric}_ts_noisy_channels_{channel_type}_percentage"] = 0.0
                row[f"{metric}_ts_flat_channels_{channel_type}_percentage"] = 0.0
        pd.DataFrame([row]).to_csv(
            metrics / f"desc-GlobalQualityIndexAttempt1_{modality}.tsv",
            sep="\t", index=False,
        )
        datasets.append(dataset)

    output = tmp_path / "custom" / "comparison.html" if explicit_output else None
    result = make_dataset_qc_plots_multi_meg_qc(
        list(map(str, datasets)), output_html=str(output) if output else None,
        analysis_mode="non-profile",
    )

    default_reports = datasets[0] / "derivatives" / "MEEGqc" / "reports"
    reports = output.parent if output else default_reports
    for modality in ("meg", "eeg"):
        generated = list(
            (reports / modality).glob(f"desc-multiDatasetQcReport*_{modality}.html")
        )
        assert len(generated) == 1
        html = generated[0].read_text(encoding="utf-8")
        assert "<html" in html
        assert f"dataset-{modality}" in html

    if output:
        assert result == output
        html = output.read_text(encoding="utf-8")
        assert "dataset-meg" in html and "dataset-eeg" in html
        for dataset in datasets:
            assert not list((dataset / "derivatives" / "MEEGqc").rglob("*.html"))
    else:
        assert result.is_file()
        assert result.parent == default_reports / "meg"
        assert not list(default_reports.glob("*.html"))
