# Rebranding: MEGqc -> MEEGqc

This document records the rebrand of the project from **MEGqc** to **MEEGqc**, what changed at each layer, and what deliberately did not change.

The rebrand reflects first-class EEG support alongside MEG. The new name (MEEGqc = MEG + EEG QC) replaces MEGqc as the public identity. Internal Python identifiers (`meg_qc`, `meg-qc` on PyPI) stay for backwards compatibility, joined by `meeg_qc` / `meeg-qc` as the rebrand-aligned aliases.

---

## What changed at a glance

| Layer                       | MEGqc                          | MEEGqc                                            |
|-----------------------------|--------------------------------|---------------------------------------------------|
| GitHub upstream             | `ANCPLabOldenburg/MEGqc`       | `ANCPLabOldenburg/MEEGqc` (renamed by lab)         |
| GitHub fork                 | `karellopez/MEGqc`             | `karellopez/MEEGqc`                                |
| Local workspace dir         | `MEGqc/`                       | `MEEGqc/`                                          |
| PyPI distribution (primary) | `meg-qc`                       | `meg-qc` (unchanged)                               |
| PyPI distribution (alias)   | n/a                            | `meeg-qc` (new meta-package, ships from this repo) |
| Python import name          | `meg_qc`                       | `meg_qc` (unchanged, see "What did NOT change")    |
| GUI title / labels          | "MEGqc"                        | "MEEGqc"                                           |
| CLI commands                | `megqc`, `run-megqc`, etc.     | both `megqc` AND `meegqc`, etc. (aliases)           |
| Launcher app name           | `MEGqc.app` / `MEGqc.desktop`  | `MEEGqc.app` / `MEEGqc.desktop`                    |
| Install dir (per-user)      | `~/MEGqc/`                     | `~/MEEGqc/`                                        |
| QSettings store             | `("ANCP", "MEGqc")`            | `("ANCP", "MEEGqc")` (with one-shot migration)     |
| Linux fallback config dir   | `~/.config/MEGqc/`             | `~/.config/MEEGqc/` (with one-shot migration)      |

---

## Where the rebrand was applied

### 1. GitHub repositories

Upstream `ANCPLabOldenburg/MEGqc` was renamed by the lab to `ANCPLabOldenburg/MEEGqc`. GitHub installed a permanent 301 redirect on the old URL.

The working fork was renamed similarly: `karellopez/MEGqc` -> `karellopez/MEEGqc`. The local `origin` remote was updated to the new URL; the old URL still resolves via the 301 but `git remote set-url` makes future operations explicit.

The local workspace directory was renamed: `MEGqc/` -> `MEEGqc/`.

### 2. PyPI distributions (lockstep release)

The repository now ships **two** PyPI distributions, released in lockstep at the same version:

- **`meg-qc`** (main distribution): the canonical, long-standing PyPI name. Every line of code lives here. Existing users, CI pipelines, shell aliases, and pinned `requirements.txt` files continue working unchanged.
- **`meeg-qc`** (meta-package at `packaging/meeg-qc/`): a thin distribution that declares `meg_qc == X.Y.Z` as its only dependency. Ships zero Python code. Installing it pulls in `meg-qc`. Same end state as `pip install meg-qc`, but reachable under the rebrand-aligned name.

Both distributions are released together via the `release.py` script at the repo root, which keeps the version field in both `pyproject.toml` files in sync plus the exact `meg_qc == X.Y.Z` pin inside the wrapper.

### 3. CLI commands

Each existing console script gained a `meeg*` sibling pointing at the **same Python function**. No code duplication, no separate dispatch. All ten scripts ship in the single `meg-qc` wheel.

| Original (kept)        | New alias (added)        | Function it dispatches to                                |
|------------------------|--------------------------|----------------------------------------------------------|
| `megqc`                | `meegqc`                 | `meg_qc.miscellaneous.GUI.megqcGUI:run_megqc_gui`        |
| `run-megqc`            | `run-meegqc`             | `meg_qc.test:run_megqc`                                  |
| `run-megqc-plotting`   | `run-meegqc-plotting`    | `meg_qc.test:get_plots`                                  |
| `get-megqc-config`     | `get-meegqc-config`      | `meg_qc.test:get_config`                                 |
| `globalqualityindex`   | (no rename: no "megqc" in name) | `meg_qc.test:run_gqi`                            |

`--help` output adapts to the invocation name. If the user typed `run-meegqc --help`, every example in the description reads `run-meegqc`; if they typed `run-megqc --help`, it reads `run-megqc`. Internally consistent regardless of alias choice. The brand prose in help text always reads "MEEGqc" because the brand is what's been renamed, not the implementation.

### 4. GUI

User-visible "MEGqc" was replaced with "MEEGqc" across the GUI subtree:

- Main window title.
- Bottom-row version label (`MEEGqc v1.0.x`).
- Tooltips on "Check updates" and "Open CLI".
- QC Viewer window title, About-dialog HTML, menu actions ("Load MEEGqc Annotations..."), GroupBox labels ("MEEGqc Annotation Overlays").
- Live Terminal window title ("MEEGqc - Live Terminal Output").
- "Open CLI" terminal banner: lists both `meg-*` and `meeg-*` command families side by side, explaining they dispatch to the same code.
- All early-startup `[MEGqc]` log prefixes -> `[MEEGqc]`.
- HTTP `User-Agent` in the PyPI update check.
- Module docstrings across `updater.py`, `update_widgets.py`, `worker_entry.py`, `output_monitoring/`, `qc_viewer/`.
- Argparse `--help` descriptions and example strings in `meg_qc/test.py`.

### 5. Persistence migration (one-shot, idempotent)

User state previously written under the old brand is migrated to the new names on first launch. The migration is wrapped in a marker key inside the new QSettings store, so it runs exactly once even on platforms (macOS) where `QSettings.allKeys()` returns inherited global system preferences and can't be used as an emptiness check.

Migrated stores:

1. **Main GUI QSettings**: `QSettings("ANCP", "MEGqc")` -> `QSettings("ANCP", "MEEGqc")`. Key copied: `ui/theme`.
2. **QC Viewer QSettings**: `QSettings("ANCP", "MEGqc_Viewer")` -> `QSettings("ANCP", "MEEGqc_Viewer")`. Key copied: `viewer/dark_plot`.
3. **Linux fallback config dir**: `~/.config/MEGqc/` -> `~/.config/MEEGqc/` (atomic `shutil.move`).

The migration function (`_migrate_legacy_megqc_state` in `meg_qc/miscellaneous/GUI/megqcGUI.py`) swallows every exception so a broken migration never blocks startup. Worst case: the user re-picks their theme.

Marker key (sentinel): `_migration/megqc_to_meegqc` inside the new main QSettings store. Once set, all three migrations are skipped on subsequent launches.

### 6. Installers

Brand pass on the bootstrap installers under `installers/installers/`:

- Renamed scripts: `install_MEGqc.{command,sh,bat}` -> `install_MEEGqc.{command,sh,bat}`.
- All three: window titles, banner ASCII, install dir (`~/MEGqc` -> `~/MEEGqc`), launcher app names, bundle identifier (macOS), launcher binary name (e.g., `MEEGqc.app` / `MEEGqc.exe`), desktop entry names, icon filenames, log filenames, GitHub URLs.
- The `installers.zip` rolled-up artefact was rebuilt to match.

**Kept unchanged on purpose**:
- `PYPI_PKG="meg-qc"` in all three installers. Existing users keep upgrading the canonical package; they do not need to know `meeg-qc` exists. The wrapper is for new users discovering the tool under its current branding.
- The CLI invocation inside the launcher (`exec megqc "$@"` on macOS / Linux, `echo megqc %*` on Windows). The launcher calls the legacy CLI entry point - both work, but keeping `megqc` here means the launcher script doesn't have to be updated for the next rebrand iteration.

### 7. App icon (Linux installer regression fix)

The Linux installer's icon resolution had been falling through to `logo.png` (a wide wordmark) because the `AppIcon{16..1024}.png` files it expected at `assets/macos/AppIcon256.png` did not exist on disk. `pyproject.toml`'s `package-data` listed them, but setuptools silently skips missing entries, so the wheel had never actually shipped them.

Fix: extracted PNGs from `assets/macos/AppIcon.icns` using `iconutil` on macOS, and committed the seven `AppIcon{16,32,64,128,256,512,1024}.png` files. Six of seven are pixel-perfect copies of the embedded iconset art; the 16-pixel slot is a LANCZOS downscale of the 32-pixel art (the .icns has no native 16-pixel variant).

### 8. Documentation references

- `CLAUDE.md` (workspace root, outside this repo): the sibling-projects row was updated to point at the new GitHub URL + local path.
- Memory notes that referenced the old paths were updated.

---

## What did NOT change

### Internal Python identifiers

- **`meg_qc` import name** stays. Renaming it would break every downstream `import meg_qc` in user code, CI pipelines, and notebooks. There is no `meeg_qc` Python module: `import meeg_qc` deliberately does not work.
- **`meg-qc` PyPI distribution** stays. The wrapper `meeg-qc` is additive, not replacement.
- **Internal source paths** (`meg_qc/miscellaneous/GUI/...`, `meg_qc.test:...`, etc.) stay. These are referenced from setup.py-style entry-point declarations and from the runtime code; renaming them would be a massive churn for zero observable user benefit.
- **`MEGQC_VERSION` constant import** in `megqcGUI.py` stays. Pure module-level constant, no user-facing surface.

### CLI commands under the old name

All five original CLI commands continue to work indefinitely. The rebrand is additive at the CLI layer too: anyone with `run-megqc` in their CI scripts or shell aliases is unaffected.

### Settings store inheritance

The `ANCP` organization name (first arg to `QSettings`) stays. Only the application name (second arg) was rebranded. This keeps macOS Application Support and Linux/Windows registry paths under the same lab-level umbrella.

---

## File-level summary

### Files added

| Path                                                              | Purpose                                                                 |
|-------------------------------------------------------------------|-------------------------------------------------------------------------|
| `packaging/meeg-qc/pyproject.toml`                                | Build definition for the meta-package distribution.                     |
| `packaging/meeg-qc/README.md`                                     | User-facing explanation of the alias relationship.                      |
| `packaging/meeg-qc/LICENSE`                                       | MIT licence (matches main).                                             |
| `release.py`                                                      | Lockstep version bump + build + (optional) twine upload for both PyPI distributions. |
| `meg_qc/miscellaneous/GUI/updater.py`                             | Qt-free PyPI version-check helpers (stable only).                       |
| `meg_qc/miscellaneous/GUI/_update_helper.py`                      | Detached self-update process (Windows-safe; waits for GUI to exit).     |
| `meg_qc/miscellaneous/GUI/update_widgets.py`                      | Qt-bound update notification widgets + startup check.                   |
| `meg_qc/miscellaneous/GUI/assets/macos/AppIcon{16..1024}.png`     | Seven app-icon PNG sizes extracted from the bundled `.icns`.            |

### Files removed

| Path                          | Reason                                                                     |
|-------------------------------|----------------------------------------------------------------------------|
| `versioneer.py`               | Dead code: not configured in `pyproject.toml` (static version field used). |
| `meg_qc/_version.py`          | Stale snapshot, not imported anywhere.                                     |
| `docs/Makefile`               | Old Sphinx scaffold; docs are now in `bids_manager_documentation`-style static HTML at `karellopez/megqc_documentation`. |
| `docs/make.bat`               | Same as above.                                                             |
| `docs/source/*.rst`           | Old Sphinx source files.                                                   |
| `docs/build/`                 | Old Sphinx build output.                                                   |

### Files renamed / moved

| Old path                                            | New path                                                |
|-----------------------------------------------------|---------------------------------------------------------|
| `installers/installers/MacOS/install_MEGqc.command` | `installers/installers/MacOS/install_MEEGqc.command`    |
| `installers/installers/Linux/install_MEGqc.sh`      | `installers/installers/Linux/install_MEEGqc.sh`         |
| `installers/installers/Windows/install_MEGqc.bat`   | `installers/installers/Windows/install_MEEGqc.bat`      |
| `EEG_Support_in_MEGqc.md`                           | `docs/EEG_Support_in_MEGqc.md`                          |

### Files heavily modified

- `pyproject.toml` - added four `meeg-*` console scripts alongside the existing five; bumped `Homepage` URL to the renamed upstream.
- `meg_qc/miscellaneous/GUI/megqcGUI.py` - rebranded all user-visible strings; deleted ~270 lines of the old in-process self-update code; wired in the new `updater.py` / `update_widgets.py` system; added the persistence migration function; added the app-wide window icon (`app.setWindowIcon(...)` so every sub-window inherits).
- `meg_qc/test.py` - added `_invocation_name()` + `_plotting_invocation()` helpers so `--help` adapts to the alias the user typed; rebranded description prose to MEEGqc.
- All three installer scripts - brand pass per the rules in section 6.

---

## Going forward

### Releasing a new version

```bash
cd MEEGqc
../.venv/bin/python release.py 1.0.6              # bump + build both wheels
../.venv/bin/python release.py 1.0.6 --upload     # bump + build + twine upload
```

`release.py` keeps the version field in both `pyproject.toml` files in sync plus the exact `meg_qc == X.Y.Z` pin inside the wrapper. It refuses to upload without building, validates the semver format, and prints the git commit / tag / push commands at the end. See `release.py --help`.

### Updating user-visible strings

The brand string `MEEGqc` should now be the only one used in any new user-visible text. The exceptions, all enforced by greps in CI-style checks, are:

- Inside `_migrate_legacy_megqc_state()` in `megqcGUI.py` - the legacy names are intentionally referenced as the source of the migration.
- Inside `release.py`'s prompts and `MEMORY.md` notes - workspace-level meta.

### Removing the legacy CLI names (someday)

Not planned. Five extra entry points cost nothing, and removing them would break user scripts. They stay indefinitely.

### Removing the meta-package (someday)

Not planned either. The wrapper is the rebrand-aligned name; removing it would either force users back to the old name or require yet another rebrand cycle.
