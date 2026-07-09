#!/usr/bin/env python
"""Generate tiny 10-second BIDS fixtures from full MEG/EEG datasets.

The real datasets are far too large to ship to CI. This script crops each
recording to a few seconds and re-saves it, producing a small BIDS tree per
source dataset plus a ``MANIFEST.json`` describing what was written. The result
is bundled and hosted (a GitHub Release asset), and the CI test suite runs
against it.

Every dataset is kept in its ORIGINAL format. Cropping means re-saving, so:

* FIF (MEG)              -> native ``raw.save`` (format preserved)
* EEGLAB ``.set``       -> ``mne.export`` via ``eeglabio``
* EDF                   -> ``mne.export`` via ``edfio``
* BrainVision ``.vhdr`` -> ``mne.export`` via ``pybv``
* CTF ``.ds``           -> MNE has no CTF writer, so the ``.ds`` is cropped in
                           place at the binary level: the trial-major ``.meg4``
                           is truncated to the first N whole trials and the
                           ``no_trials`` field in the ``.res4`` header is
                           patched. The dataset stays native CTF and re-reads
                           cleanly with ``mne.io.read_raw_ctf``. Only
                           multi-trial CTF recordings are supported (all of ours
                           are); a res4 MNE cannot parse is skipped (MEEGqc
                           could not read it either).

Generator-only dependencies (NOT runtime deps of MEEGqc): ``edfio``,
``eeglabio``, ``pybv`` (plus ``mne`` and ``pandas``).

Usage
-----
    python make_test_fixtures.py \
        --meg-root /path/to/meg_datasets \
        --eeg-root /path/to/eeg_datasets \
        --out      /path/to/meegqc_test_data \
        --seconds 10 --max-subs 2

Then bundle and (optionally) upload::

    tar -czf meegqc_test_data.tar.gz -C /path/to meegqc_test_data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import sys
from glob import glob

import numpy as np
import mne

mne.set_log_level("ERROR")

# CTF res4 fixed-header offsets (big-endian), verified against MNE's res4 reader.
_CTF_RES4_NSAMP_OFF = 1288       # int32: samples per trial
_CTF_RES4_NO_TRIALS_OFF = 1312   # int16: number of trials
_CTF_MEG4_HEADER = 8             # bytes of ".meg4" identity header


def _crop_ctf_ds(src_ds: str, out_ds: str, seconds: float):
    """Crop a CTF ``.ds`` in place, keeping the native CTF format.

    CTF ``.meg4`` is trial-major, each trial channel-major (``[trial][ch][sample]``).
    Trials can be short (1 s) or very long (a whole continuous run), so we do not
    keep whole trials. Instead we extract the first ``seconds`` of continuous
    samples and rewrite the ``.meg4`` as one short trial of ``K`` samples,
    patching ``no_trials`` -> 1 and ``nsamp`` -> ``K`` in the ``.res4``. Returns
    ``(out_ds, label, seconds_kept, raw)`` and re-reads cleanly with
    ``mne.io.read_raw_ctf``.
    """
    from mne.io.ctf.res4 import _read_res4
    r = _read_res4(src_ds)
    nchan, nsamp = int(r["nchan"]), int(r["nsamp"])
    no_trials, sfreq = int(r["no_trials"]), float(r["sfreq"])
    total = no_trials * nsamp
    K = max(1, min(total, int(round(seconds * sfreq))))
    trials_needed = int(math.ceil(K / nsamp))

    os.makedirs(out_ds, exist_ok=True)
    src_meg4 = None
    for f in sorted(os.listdir(src_ds)):
        s = os.path.join(src_ds, f)
        low = f.lower()
        # CTF splits data >2GB into continuation files (.meg4, .1_meg4, .2_meg4).
        # Skip ALL of them; we write only the cropped primary chunk.
        if low.endswith("meg4"):
            if low.endswith(".meg4") and src_meg4 is None:
                src_meg4 = s          # the primary (first) data chunk
            continue
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(out_ds, f))
    if src_meg4 is None:
        raise ValueError("no .meg4 in CTF dataset")
    out_meg4 = os.path.join(out_ds, os.path.basename(src_meg4))
    out_res4 = next(os.path.join(out_ds, f) for f in os.listdir(out_ds)
                    if f.lower().endswith(".res4"))
    header = open(src_meg4, "rb").read(_CTF_MEG4_HEADER)

    # Size the memmap by the ACTUAL primary .meg4 (CTF splits >2GB data across
    # continuation files, and never splits a trial across files).
    trial_bytes = nchan * nsamp * 4
    avail_trials = (os.path.getsize(src_meg4) - _CTF_MEG4_HEADER) // trial_bytes
    if avail_trials < trials_needed:
        raise ValueError(
            f"CTF crop needs {trials_needed} trial(s) but the primary .meg4 holds "
            f"{avail_trials} (oversized/multi-file trial); skipping")
    data = np.memmap(src_meg4, dtype=">i4", mode="r", offset=_CTF_MEG4_HEADER,
                     shape=(avail_trials, nchan, nsamp))
    if trials_needed == 1:
        cont = np.ascontiguousarray(data[0][:, :K])           # reads only K cols
    else:
        block = np.array(data[:trials_needed])                # short trials only
        cont = np.ascontiguousarray(block.transpose(1, 0, 2).reshape(nchan, -1)[:, :K])
    with open(out_meg4, "wb") as fo:
        fo.write(header)
        cont.astype(">i4").tofile(fo)

    _patch_res4_int(out_res4, _CTF_RES4_NO_TRIALS_OFF, ">h", no_trials, 1)
    _patch_res4_int(out_res4, _CTF_RES4_NSAMP_OFF, ">i", nsamp, K)

    raw = mne.io.read_raw_ctf(out_ds, preload=False, verbose="ERROR")  # validate
    got = raw.n_times / raw.info["sfreq"]
    if got > seconds * 2 + 1:   # safety net: the crop must have actually reduced it
        raise ValueError(f"CTF crop did not reduce duration (got {got:.0f}s); skipping")
    return out_ds, f"{K} samples", got, raw


def _patch_res4_int(res4_path: str, offset: int, fmt: str, expected: int, new: int) -> None:
    """Overwrite a big-endian int in the .res4 header, guarding the offset."""
    with open(res4_path, "r+b") as f:
        f.seek(offset)
        cur = struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
        if cur != expected:   # never corrupt an unexpected layout
            raise ValueError(f"res4 offset {offset} mismatch (got {cur}, want {expected})")
        f.seek(offset)
        f.write(struct.pack(fmt, new))

# Raw extensions we know how to read, in BIDS priority order per modality.
_MEG_EXTS = (".fif", ".ds", ".con", ".sqd", ".kdf", ".mff")
_EEG_EXTS = (".set", ".edf", ".bdf", ".vhdr", ".cnt", ".mff", ".fif")

# Sidecar suffixes copied alongside a cropped recording (same BIDS stem).
_STEM_SIDECARS = ("_channels.tsv", "_events.tsv", "_electrodes.tsv")
# Session/subject-scoped sidecars (no run/task entities).
_SES_SIDECARS = ("coordsystem.json",)
_ROOT_FILES = ("dataset_description.json", "participants.tsv", "participants.json",
               "README", "README.md", "CHANGES", "task-*_events.json")


def _read_raw(path: str):
    """Dispatch to the right MNE reader by extension. Returns (raw, ext)."""
    low = path.lower()
    if low.endswith(".fif") or low.endswith(".fif.gz"):
        return mne.io.read_raw_fif(path, preload=False, allow_maxshield=True), ".fif"
    if low.endswith(".ds"):
        return mne.io.read_raw_ctf(path, preload=False, verbose="ERROR"), ".ds"
    if low.endswith(".set"):
        return mne.io.read_raw_eeglab(path, preload=True, verbose="ERROR"), ".set"
    if low.endswith(".edf"):
        return mne.io.read_raw_edf(path, preload=False, verbose="ERROR"), ".edf"
    if low.endswith(".bdf"):
        return mne.io.read_raw_bdf(path, preload=False, verbose="ERROR"), ".bdf"
    if low.endswith(".vhdr"):
        return mne.io.read_raw_brainvision(path, preload=False, verbose="ERROR"), ".vhdr"
    if low.endswith(".mff"):
        return mne.io.read_raw_egi(path, preload=False, verbose="ERROR"), ".mff"
    if low.endswith((".con", ".sqd")):
        return mne.io.read_raw_kit(path, preload=False, verbose="ERROR"), ".con"
    raise ValueError(f"No reader for {path}")


def _save_crop(raw, ext: str, out_stem: str) -> tuple[str, str | None]:
    """Save a cropped raw. Returns (written_path, converted_from-or-None)."""
    if ext == ".fif":
        out = out_stem + "_meg.fif"
        raw.save(out, overwrite=True, verbose="ERROR")
        return out, None
    if ext == ".set":
        out = out_stem + "_eeg.set"
        mne.export.export_raw(out, raw, fmt="eeglab", overwrite=True, verbose="ERROR")
        return out, None
    if ext in (".edf", ".bdf"):
        out = out_stem + "_eeg.edf"
        mne.export.export_raw(out, raw, fmt="edf", overwrite=True, verbose="ERROR")
        return out, None
    if ext == ".vhdr":
        out = out_stem + "_eeg.vhdr"
        mne.export.export_raw(out, raw, fmt="brainvision", overwrite=True, verbose="ERROR")
        return out, None
    # CTF ".ds" is handled separately by _crop_ctf_ds (native, no conversion).
    # Any other unwritable format is skipped rather than converted, to honor the
    # keep-original-format policy.
    raise ValueError(f"no native writer for {ext}; skipped (keep-original policy)")


def _copy_sidecars(src_dir: str, stem: str, out_dir: str, seconds: float,
                   sub: str, ses: str | None) -> None:
    import pandas as pd
    # stem-scoped sidecars (channels/events/electrodes)
    for suff in _STEM_SIDECARS:
        s = os.path.join(src_dir, stem + suff)
        if not os.path.exists(s):
            continue
        d = os.path.join(out_dir, stem + suff)
        if suff == "_events.tsv":
            df = pd.read_csv(s, sep="\t")
            if "onset" in df.columns:
                df = df[df["onset"].astype(float) < seconds]
            df.to_csv(d, sep="\t", index=False)
        else:
            shutil.copy2(s, d)
    # session-scoped sidecars (coordsystem etc.)
    ses_prefix = f"{sub}_{ses}_" if ses else f"{sub}_"
    for suff in _SES_SIDECARS:
        for s in glob(os.path.join(src_dir, f"{ses_prefix}*{suff}")) + \
                 glob(os.path.join(src_dir, f"*{suff}")):
            shutil.copy2(s, os.path.join(out_dir, os.path.basename(s)))
    # sidecar JSON for the recording (task/run scoped): copy the .json peer if any
    for peer in glob(os.path.join(src_dir, stem + "_*.json")):
        shutil.copy2(peer, os.path.join(out_dir, os.path.basename(peer)))


def _first_recording(sub_dir: str, exts: tuple[str, ...]) -> str | None:
    """Return the first raw recording path under a subject folder for these exts."""
    for ext in exts:
        # meg/eeg datatype folders, with or without a session level
        hits = sorted(glob(os.path.join(sub_dir, "**", f"*{ext}"), recursive=True))
        hits = [h for h in hits if "/derivatives/" not in h]
        if hits:
            # for .ds this yields the directory; for files the file
            return hits[0]
    return None


def _process_dataset(ds_dir: str, out_ds: str, exts: tuple[str, ...],
                     seconds: float, max_subs: int, records: list) -> None:
    subs = sorted(d for d in glob(os.path.join(ds_dir, "sub-*")) if os.path.isdir(d))
    subs = subs[:max_subs]
    if not subs:
        return
    os.makedirs(out_ds, exist_ok=True)
    # root files
    for pat in _ROOT_FILES:
        for s in glob(os.path.join(ds_dir, pat)):
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(out_ds, os.path.basename(s)))

    for sub_dir in subs:
        sub = os.path.basename(sub_dir)
        rec = _first_recording(sub_dir, exts)
        if not rec:
            continue
        rel = os.path.relpath(rec, sub_dir)  # e.g. ses-1/meg/sub-..._meg.fif
        parts = rel.split(os.sep)
        ses = parts[0] if parts[0].startswith("ses-") else None
        src_dir = os.path.dirname(rec)
        out_rec_dir = os.path.join(out_ds, os.path.relpath(src_dir, ds_dir))
        os.makedirs(out_rec_dir, exist_ok=True)
        stem = os.path.basename(rec)
        for e in (".fif", ".ds", ".set", ".edf", ".bdf", ".vhdr", ".mff", ".con", ".sqd"):
            if stem.lower().endswith(e):
                stem = stem[: -len(e)]
                break
        stem = stem.rsplit("_", 1)[0] if stem.endswith(("_meg", "_eeg")) else stem
        try:
            if rec.lower().endswith(".ds"):
                # CTF: crop the .ds in place (native format), no MNE re-write.
                out_ds_path = os.path.join(out_rec_dir, stem + "_meg.ds")
                _, keep, secs_kept, raw = _crop_ctf_ds(rec, out_ds_path, seconds)
                _copy_sidecars(src_dir, stem, out_rec_dir, seconds, sub, ses)
                records.append({
                    "dataset": os.path.basename(out_ds), "subject": sub, "session": ses,
                    "modality": "meg", "source_format": "ctf", "converted_from": None,
                    "written": os.path.relpath(out_ds_path, os.path.dirname(out_ds)),
                    "seconds": round(secs_kept, 3), "n_channels": len(raw.ch_names),
                    "sfreq": float(raw.info["sfreq"]),
                })
                print(f"  {sub}: .ds -> {os.path.basename(out_ds_path)} "
                      f"({secs_kept:.0f}s, {keep} trials, {len(raw.ch_names)} ch, native CTF)")
                continue
            raw, ext = _read_raw(rec)
            dur = float(raw.times[-1])
            raw.crop(tmax=min(seconds, dur))
            if not raw.preload:
                raw.load_data(verbose="ERROR")
            out_stem = os.path.join(out_rec_dir, stem)
            written, converted = _save_crop(raw, ext, out_stem)
            _copy_sidecars(src_dir, stem, out_rec_dir, seconds, sub, ses)
            records.append({
                "dataset": os.path.basename(out_ds),
                "subject": sub, "session": ses,
                "modality": "eeg" if written.endswith(("_eeg.set", "_eeg.edf", "_eeg.vhdr")) else "meg",
                "source_format": ext.lstrip("."),
                "written": os.path.relpath(written, os.path.dirname(out_ds)),
                "converted_from": converted,
                "seconds": round(min(seconds, dur), 3),
                "n_channels": len(raw.ch_names),
                "sfreq": float(raw.info["sfreq"]),
            })
            print(f"  {sub}: {ext} -> {os.path.basename(written)} "
                  f"({min(seconds, dur):.0f}s, {len(raw.ch_names)} ch)")
        except Exception as exc:  # noqa: BLE001
            print(f"  {sub}: SKIP ({exc})")
            records.append({"dataset": os.path.basename(out_ds), "subject": sub,
                            "error": str(exc)})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meg-root", required=True)
    ap.add_argument("--eeg-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--max-subs", type=int, default=2)
    args = ap.parse_args()

    if os.path.exists(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out, exist_ok=True)
    records: list = []

    for root, exts, tag in ((args.meg_root, _MEG_EXTS, "MEG"),
                            (args.eeg_root, _EEG_EXTS, "EEG")):
        for ds_dir in sorted(glob(os.path.join(root, "*"))):
            if not os.path.isdir(ds_dir):
                continue
            name = os.path.basename(ds_dir)
            print(f"[{tag}] {name}")
            _process_dataset(ds_dir, os.path.join(args.out, name), exts,
                             args.seconds, args.max_subs, records)

    ok = [r for r in records if "error" not in r]
    manifest = {
        "seconds": args.seconds, "max_subs": args.max_subs,
        "n_datasets": len({r["dataset"] for r in ok}),
        "n_recordings": len(ok),
        "recordings": records,
    }
    with open(os.path.join(args.out, "MANIFEST.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\nDONE: {manifest['n_recordings']} recordings across "
          f"{manifest['n_datasets']} datasets -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
