"""get-meegqc-config writes a valid settings.ini (no fixture data needed)."""
import configparser
import shutil
import subprocess

import pytest


def test_get_config_writes_valid_ini(tmp_path):
    exe = shutil.which("get-meegqc-config")
    if exe is None:
        pytest.skip("get-meegqc-config not on PATH (package not installed?)")
    r = subprocess.run([exe, "--target_directory", str(tmp_path), "--filename", "settings.ini"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    ini = tmp_path / "settings.ini"
    assert ini.is_file()
    cp = configparser.ConfigParser()
    cp.read(ini)
    assert "GENERAL" in cp
    assert "GlobalQualityIndex" in cp
    assert cp.has_option("Epoching", "epoching_strategy")
    assert cp.get("Epoching", "epoching_strategy") in ("auto", "events", "fixed")
