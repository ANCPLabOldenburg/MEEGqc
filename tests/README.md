# MEEGqc test suite

Three tiers of tests:

- **Unit** (`tests/test_*.py`): fast, no data. Run anywhere.
- **Headless GUI** (`tests/gui/`): construct the Qt GUI with the offscreen
  platform and check the profile-mode controls. Needs `PyQt6` (a normal
  dependency); no display required.
- **Real-data** (`tests/realdata/`, marked `realdata`): run the CLI and the
  Python API against a bundle of tiny, 10-second, real MEG and EEG recordings in
  their native formats (FIF, CTF `.ds`, EEGLAB `.set`, EDF, BrainVision). These
  are **skipped** unless `MEEGQC_TEST_DATA` points at an unpacked bundle.

## Running locally

```bash
pip install -e .
pip install pytest

# unit + GUI only (no data):
QT_QPA_PLATFORM=offscreen pytest tests/gui tests/test_cli_get_config.py

# everything, against a fixture bundle:
export MEEGQC_TEST_DATA=/path/to/meegqc_test_data
QT_QPA_PLATFORM=offscreen pytest tests/ \
  --ignore=tests/test_group_figure.py \
  --ignore=tests/test_meg_pipeline.py \
  --ignore=tests/test_global_report.py
```

(The three ignored files are pre-existing failures unrelated to this suite: a
symbol removed in the `group -> dataset` refactor and an MNE-1.12 logging quirk.
Fix and re-enable them separately.)

## The real-data fixture bundle

The bundle is produced from full datasets by cropping every recording to 10
seconds **in its original format** and copying the BIDS sidecars, then packaged
as `meegqc_test_data.tar.gz` (~235 MB) and attached to a GitHub Release. CI
downloads and caches it by release tag (`FIXTURES_TAG` in
`.github/workflows/tests.yml`, default `test-data-v1`).

### Regenerating the bundle

`tests/fixtures/make_test_fixtures.py` crops each dataset. It needs a few
export libraries that are **not** MEEGqc runtime dependencies:

```bash
pip install mne pandas numpy edfio eeglabio pybv

python tests/fixtures/make_test_fixtures.py \
  --meg-root /path/to/meg_datasets \
  --eeg-root /path/to/eeg_datasets \
  --out      /tmp/meegqc_test_data \
  --seconds 10 --max-subs 2
```

Format handling: FIF is saved natively; EEGLAB/EDF/BrainVision are re-exported
via `eeglabio`/`edfio`/`pybv`; CTF `.ds` (which MNE cannot write) is cropped at
the binary level (the trial-major `.meg4` is rewritten to the first ~10 s of
samples and the `.res4` header is patched), so it stays native CTF. A
`MANIFEST.json` records every recording (dataset, subject, format, channels,
sampling rate) and drives the parametrized tests.

### Hosting the bundle

CI downloads the tarball from a single URL: `FIXTURES_URL` in the workflow (best
set as a repo variable under Settings -> Secrets and variables -> Actions ->
Variables, so it is not hard-coded). Any public direct-download URL works.

```bash
tar -czf meegqc_test_data.tar.gz -C /tmp meegqc_test_data
```

Option A - **GitHub Release asset** (fork is fine; it does not touch the ANCP repo):

```bash
gh release create test-data-v1 meegqc_test_data.tar.gz \
  --repo <owner>/MEEGqc --title "Test data v1" \
  --notes "10 s cropped MEG/EEG fixtures for CI"
```
URL: `https://github.com/<owner>/MEEGqc/releases/download/test-data-v1/meegqc_test_data.tar.gz`

Option B - **University cloud (Nextcloud, e.g. cloud.uol.de)**: upload the
tarball, create a **public share link**, and append `/download`:
`https://cloud.uol.de/s/<share-token>/download`. Use a share **without a
password** so CI can fetch it unauthenticated (or, if it must be private, put
the whole URL in a GitHub Actions **secret** and reference it from the
workflow). Confirm it downloads with `curl -fsSL -o t.tar.gz "<url>"` locally.

Whichever you pick, set `FIXTURES_URL` to that URL. When you replace the data,
re-upload and **bump `FIXTURES_VERSION`** in the workflow so the cache key
changes and runners fetch the new bundle.

## What is covered

CLI: `get-meegqc-config`; `run-meegqc` on **every** dataset/format (BIDS-valid
derivative names asserted); the four analysis modes + legacy aliases; the
`skip` / `rerun` semantics; `run-meegqc-plotting` (subject / dataset QA + QC,
multi-dataset QA + QC); `globalqualityindex`. Python API: the `run_*_dispatch`
functions and `normalize_analysis_mode`. GUI: construction and the
profile / non-profile control blocking.

## CI matrix

`.github/workflows/tests.yml` runs the whole suite on every push and pull
request across Python 3.10 - 3.14 and six runners: Linux x64/ARM, macOS
Intel/Apple-Silicon, Windows x64, and Windows-ARM (preview, non-blocking via
`continue-on-error`).
