#!/usr/bin/env python3
"""Lockstep release for meg_qc and meeg_qc.

The two distributions ship from this repo and are always released at the
same version. This script bumps the version in both pyproject.toml files,
keeps the wrapper's exact `meg_qc==X.Y.Z` pin in sync, then builds (and
optionally uploads) both distributions.

Usage:
    python release.py NEW_VERSION [--dry-run] [--no-build] [--upload]

Examples:
    python release.py 0.9.9                  # bump + build, no upload
    python release.py 0.9.9 --dry-run        # preview only, no changes
    python release.py 0.9.9 --upload         # bump + build + twine upload
    python release.py 0.9.9 --no-build       # bump version only

Requirements:
    pip install build twine
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
MAIN_PYPROJECT = REPO_ROOT / "pyproject.toml"
WRAPPER_DIR = REPO_ROOT / "packaging" / "meeg-qc"
WRAPPER_PYPROJECT = WRAPPER_DIR / "pyproject.toml"

# Matches the top-level static `version = "..."` field in pyproject.toml.
# Anchored to start-of-line + MULTILINE so we don't match any version-looking
# string deep inside the file (e.g. classifier strings, dependency pins).
VERSION_RE = re.compile(r'^(version\s*=\s*)"([^"]+)"', re.MULTILINE)

# Matches the wrapper's exact pin on the main distribution.
MEG_QC_PIN_RE = re.compile(r'"meg_qc==[^"]+"')

# Accepts PEP 440-ish versions: X.Y.Z plus optional suffix
# (e.g. 1.2.3, 1.2.3a1, 1.2.3.dev0, 1.2.3rc1, 1.2.3.post1, 1.2.3+local.0).
VERSION_FORMAT_RE = re.compile(r"^\d+\.\d+\.\d+([a-zA-Z0-9.+-]*)?$")


def die(msg: str) -> None:
    print(f"[X] {msg}", file=sys.stderr)
    sys.exit(1)


def read_version(pyproject: Path) -> str:
    match = VERSION_RE.search(pyproject.read_text(encoding="utf-8"))
    if not match:
        die(f"could not find static version field in {pyproject}")
    return match.group(2)


def update_version(pyproject: Path, new_version: str, dry_run: bool) -> None:
    text = pyproject.read_text(encoding="utf-8")
    new_text, n = VERSION_RE.subn(rf'\1"{new_version}"', text, count=1)
    if n != 1:
        die(f"failed to update version in {pyproject} (no match)")
    if not dry_run:
        pyproject.write_text(new_text, encoding="utf-8")


def update_meg_qc_pin(pyproject: Path, new_version: str, dry_run: bool) -> None:
    text = pyproject.read_text(encoding="utf-8")
    new_text, n = MEG_QC_PIN_RE.subn(f'"meg_qc=={new_version}"', text)
    if n == 0:
        die(f"no meg_qc==... pin found in {pyproject}")
    if not dry_run:
        pyproject.write_text(new_text, encoding="utf-8")


def build_dist(label: str, work_dir: Path, dry_run: bool) -> None:
    rel = work_dir.relative_to(REPO_ROOT)
    print(f"\n[*] Building {label}  (cwd: {rel if str(rel) != '.' else 'repo root'})")
    if dry_run:
        print("    (dry-run: skipped)")
        return
    # Clean stale artefacts so we don't accidentally upload an old wheel.
    for target in ("dist", "build"):
        path = work_dir / target
        if path.exists():
            shutil.rmtree(path)
    for egg in work_dir.glob("*.egg-info"):
        shutil.rmtree(egg)
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation"],
        cwd=work_dir,
    )
    if result.returncode != 0:
        die(f"build failed for {label}")


def twine_upload(artifacts: list[Path], dry_run: bool) -> None:
    if not artifacts:
        die("no artifacts to upload (did you skip --no-build?)")
    print(f"\n[*] Uploading {len(artifacts)} files to PyPI:")
    for f in artifacts:
        print(f"    {f.relative_to(REPO_ROOT)}")
    if dry_run:
        print("    (dry-run: skipped)")
        return
    result = subprocess.run(
        ["twine", "upload", *[str(f) for f in artifacts]],
    )
    if result.returncode != 0:
        die("twine upload failed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lockstep release for meg_qc + meeg_qc.",
    )
    parser.add_argument(
        "version",
        help='New version, e.g. "0.9.9" or "1.0.0rc1". A leading "v" is stripped.',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files, building, or uploading.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip the build step (just bump the version).",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="After building, upload all artifacts to PyPI via twine.",
    )
    args = parser.parse_args()

    new_version = args.version.strip().lstrip("v")
    if not VERSION_FORMAT_RE.match(new_version):
        die(f"invalid version format: {new_version!r}")
    if args.upload and args.no_build:
        die("--upload requires a build (do not combine with --no-build)")

    main_current = read_version(MAIN_PYPROJECT)
    wrapper_current = read_version(WRAPPER_PYPROJECT)

    print(f"  meg_qc:   {main_current}  ->  {new_version}")
    print(f"  meeg_qc:  {wrapper_current}  ->  {new_version}")
    if main_current != wrapper_current:
        print(
            f"  [!] WARNING: current versions disagree "
            f"({main_current!r} vs {wrapper_current!r}); "
            f"both will be aligned to {new_version!r}."
        )

    update_version(MAIN_PYPROJECT, new_version, args.dry_run)
    update_version(WRAPPER_PYPROJECT, new_version, args.dry_run)
    update_meg_qc_pin(WRAPPER_PYPROJECT, new_version, args.dry_run)

    if args.dry_run:
        print("\n[dry-run] no files modified.")
    else:
        print("\n[+] pyproject.toml files updated.")

    if not args.no_build:
        build_dist("meg_qc",  REPO_ROOT,   args.dry_run)
        build_dist("meeg_qc", WRAPPER_DIR, args.dry_run)

    if args.upload:
        artifacts = sorted(
            list((REPO_ROOT / "dist").glob("*"))
            + list((WRAPPER_DIR / "dist").glob("*"))
        )
        twine_upload(artifacts, args.dry_run)

    if not args.dry_run:
        print("\n[i] Next steps:")
        if not args.upload and not args.no_build:
            print("    twine upload dist/* packaging/meeg-qc/dist/*")
        print("    git add pyproject.toml packaging/meeg-qc/pyproject.toml")
        print(f'    git commit -m "release: meg_qc + meeg_qc {new_version}"')
        print(f"    git tag v{new_version}")
        print("    git push && git push --tags")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
