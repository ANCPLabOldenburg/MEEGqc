"""Qt-free self-update helpers for the MEEGqc GUI.

The Windows constraint
======================

On Windows a running Python process holds file handles on its loaded
modules (especially compiled extensions: ``PyQt6/Qt6/bin/*.dll``,
``numpy/*.pyd``, ``PyQt6-WebEngine``'s Chromium binaries, ...).
``pip install --upgrade meg_qc`` invoked from inside the GUI then
fails with::

    PermissionError: [WinError 32] The process cannot access the file
    because it is being used by another process.

The workaround is to spawn a **detached** helper process that:

1. Waits for the GUI process to exit (so all file handles are released);
2. Runs ``python -m pip install --upgrade <package>``;
3. Optionally restarts the GUI.

The helper script is a stand-alone ``.py`` that gets **copied to a
temp directory** before being launched, so the running helper survives
pip replacing ``meg_qc.miscellaneous.GUI._update_helper`` on disk.

Stable-only policy
==================

``fetch_latest_pypi`` returns only the latest **stable** release. The
GUI does not surface pre-releases (alpha / beta / rc / dev / post). A
user who explicitly wants a pre-release can run ``pip install --pre
meg_qc`` outside the GUI.

Multi-distribution awareness
============================

The same code ships on PyPI as two distributions: ``meg_qc`` (the
canonical, all-code distribution) and ``meeg_qc`` (a meta-package that
pins ``meg_qc==X.Y.Z`` exactly and pulls it in). Upgrading the wrong
one breaks pip's resolver. :func:`installed_distribution_name` returns
whichever the user installed, so the update helper feeds the right
name to pip.

Failure policy
==============

Network helpers (``fetch_latest_pypi``) **never raise**. They return
``None`` on any failure (no internet, DNS error, SSL error, timeout,
malformed JSON, ...). Callers treat ``None`` as "couldn't tell".
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


# The canonical distribution that holds the actual code. The wrapper
# ``meeg_qc`` is just a meta-package that depends on this; PyPI version
# checks always target the canonical name so the answer matches
# ``meg_qc.__version__``.
PYPI_PACKAGE = "meg_qc"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"
USER_AGENT = "MEEGqc-GUI-update-check"


def installed_version() -> str:
    """Return the running meg_qc version (``meg_qc.__version__``)."""
    from meg_qc import __version__
    return str(__version__)


def installed_distribution_name() -> str:
    """Return ``'meeg_qc'`` if the wrapper is installed, else ``'meg_qc'``.

    The wrapper ``meeg_qc`` declares ``meg_qc==X.Y.Z`` as an exact pin.
    If the user installed via ``pip install meeg-qc`` and we upgrade
    ``meg_qc`` alone, pip's resolver complains and the user ends up in
    a broken state. Upgrading ``meeg_qc`` is safe because it pulls the
    matching ``meg_qc`` release in transitively.
    """
    try:
        from importlib.metadata import distribution, PackageNotFoundError
        try:
            distribution("meeg_qc")
            return "meeg_qc"
        except PackageNotFoundError:
            return "meg_qc"
    except Exception:
        return "meg_qc"


def is_editable_install() -> bool:
    """True when meg_qc is installed in editable mode (``pip install -e .``).

    Editable installs should not be auto-updated. We detect them via the
    PEP 660 ``direct_url.json`` marker that pip writes into the dist-info.
    Any error reading the metadata is treated as "not editable" so we
    err on the side of allowing updates.
    """
    try:
        from importlib.metadata import distribution, PackageNotFoundError
        try:
            dist = distribution(PYPI_PACKAGE)
        except PackageNotFoundError:
            return False
        raw = dist.read_text("direct_url.json")
        if not raw:
            return False
        data = json.loads(raw)
        return bool(data.get("dir_info", {}).get("editable"))
    except Exception:
        return False


def fetch_latest_pypi(timeout: float = 8.0) -> Optional[str]:
    """Return the latest stable version on PyPI, or ``None`` on any failure.

    Never raises. Tries certifi -> system CA -> unverified SSL, in that
    order. Returns ``None`` if every attempt fails or the response is
    not parseable.

    Pre-releases are never returned: PyPI's ``info.version`` field is
    always the latest stable release. The full ``releases`` dict is
    intentionally not consulted.
    """
    req = Request(PYPI_URL, headers={"User-Agent": USER_AGENT})
    contexts = []
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    try:
        contexts.append(ssl.create_default_context())
    except Exception:
        pass
    try:
        contexts.append(ssl._create_unverified_context())
    except Exception:
        pass

    for ctx in contexts:
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            version = str(payload.get("info", {}).get("version", "")).strip()
            return version or None
        except Exception as exc:
            log.debug("PyPI fetch attempt failed: %s", exc)
    return None


def is_newer(latest: str, current: str) -> bool:
    """Return True when *latest* is strictly newer than *current*.

    Uses ``packaging.version`` when available; falls back to a string
    comparison that at least catches the equality case correctly.
    """
    if not latest or not current:
        return False
    try:
        from packaging.version import Version
        return Version(latest) > Version(current)
    except Exception:
        return latest != current


# ---------------------------------------------------------------------------
# Detached-helper spawn
# ---------------------------------------------------------------------------


def _python_executable() -> str:
    """Best-effort path to the venv's Python interpreter.

    ``sys.executable`` is the running interpreter, which is exactly the
    one pip needs to upgrade the package it's already imported from.
    """
    return sys.executable or "python"


def _copy_helper_to_temp() -> Path:
    """Copy ``_update_helper.py`` to a temp dir + return the new path.

    The copy isolates the running helper from any pip operation that
    may replace files inside the installed ``meg_qc.miscellaneous.GUI``
    package.
    """
    src = Path(__file__).with_name("_update_helper.py")
    tmpdir = Path(tempfile.mkdtemp(prefix="meg_qc-update-"))
    dst = tmpdir / "_update_helper.py"
    shutil.copy2(src, dst)
    return dst


def launch_update_helper(*, restart: bool = True) -> bool:
    """Spawn the detached helper, then return.

    The caller is expected to immediately quit the GUI so the helper
    can replace the package files. Returns ``True`` if the spawn call
    itself succeeded; the actual pip install runs after this returns.
    """
    try:
        helper = _copy_helper_to_temp()
    except Exception as exc:
        log.error("Could not stage update helper: %s", exc)
        return False

    python = _python_executable()
    parent_pid = os.getpid()
    package = installed_distribution_name()

    cmd = [
        python, str(helper),
        "--parent-pid", str(parent_pid),
        "--python", python,
        "--package", package,
    ]
    if restart:
        # Restart by re-launching the same entry point the user just
        # used. ``sys.argv[0]`` is e.g. ``.../env/Scripts/megqc.exe``
        # on Windows or ``.../env/bin/megqc`` on POSIX.
        cmd += ["--restart-cmd", sys.argv[0]]

    try:
        if platform.system() == "Windows":
            # CREATE_NEW_CONSOLE pops a visible console window for pip's
            # output. DETACHED_PROCESS would hide it but the user gets
            # no feedback during a multi-minute pip install.
            CREATE_NEW_CONSOLE = 0x00000010
            CREATE_BREAKAWAY_FROM_JOB = 0x01000000
            flags = CREATE_NEW_CONSOLE | CREATE_BREAKAWAY_FROM_JOB
            subprocess.Popen(
                cmd,
                creationflags=flags,
                close_fds=True,
            )
        else:
            # POSIX: detach into a new session so SIGHUP from the GUI
            # exit doesn't take the helper down with it. Output goes to
            # ~/.meg_qc/update.log so the user can debug if needed.
            log_path = Path.home() / ".meg_qc" / "update.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "ab", buffering=0)
            subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        return True
    except Exception as exc:
        log.error("Could not spawn update helper: %s", exc)
        return False


__all__ = [
    "PYPI_PACKAGE",
    "fetch_latest_pypi",
    "installed_distribution_name",
    "installed_version",
    "is_editable_install",
    "is_newer",
    "launch_update_helper",
]
