# meeg-qc

`meeg-qc` is the new name for the MEG and EEG quality control tool previously published as `meg-qc` (and branded as MEGqc). The lab has rebranded to **MEEGqc** to reflect first-class EEG support alongside MEG.

This distribution is a thin meta-package: installing it pulls in `meg-qc`, which is where all the code, CLI entry points, and package data live.

## Install

```bash
pip install meeg-qc
```

is equivalent to:

```bash
pip install meg-qc
```

Both deliver the same installed result: the `meg_qc` Python package plus every CLI entry point in both naming families (`megqc`, `run-megqc`, `run-megqc-plotting`, `get-megqc-config`, `globalqualityindex`, **and** the new `meegqc`, `run-meeqc`, `run-meeqc-plotting`, `get-meeqc-config` aliases that point at the same underlying functions).

The Python import name remains `meg_qc`:

```python
import meg_qc        # works
import meeg_qc       # does NOT work - intentional, no module shim
```

## Why two distributions?

- `meg-qc` is the canonical, long-standing PyPI name. Existing users, CI pipelines, and shell aliases keep working with no change.
- `meeg-qc` is the rebrand-aligned name for new users discovering the tool under its current branding.

Both ship from the same source repository (`ANCPLabOldenburg/MEEGqc`) and are released together at the same version.

## Source

https://github.com/ANCPLabOldenburg/MEEGqc

## License

MIT - see `LICENSE`.
