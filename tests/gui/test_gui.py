"""Headless GUI tests (offscreen). Cover construction + the profile-mode controls."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def main_window(qapp):
    from meg_qc.miscellaneous.GUI.megqcGUI import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_window_constructs(main_window):
    assert main_window.isVisible() in (True, False)  # constructed without raising


def test_analysis_mode_options_are_canonical(main_window):
    cmb = main_window.cmb_analysis_mode
    data = [cmb.itemData(i) for i in range(cmb.count())]
    assert data == ["non-profile", "new-profile", "reuse-profile", "latest-profile"]


def test_non_profile_disables_profile_controls(main_window):
    w = main_window
    w._set_analysis_mode("non-profile")
    assert not w.edit_analysis_id.isEnabled()
    assert not w.btn_load_profiles.isEnabled()
    assert not w.btn_refresh_profiles.isEnabled()

    w._set_analysis_mode("reuse-profile")
    assert w.edit_analysis_id.isEnabled()
    assert w.btn_load_profiles.isEnabled()
    assert w.btn_refresh_profiles.isEnabled()


def test_collect_returns_canonical_mode(main_window):
    main_window._set_analysis_mode("new-profile")
    mode, analysis_id, cfg_policy, sub_policy = main_window._collect_analysis_profile_settings()
    assert mode == "new-profile"
    assert cfg_policy in ("provided", "latest_saved", "fail")
    assert sub_policy in ("skip", "rerun", "fail")
