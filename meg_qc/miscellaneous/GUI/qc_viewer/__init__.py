"""
qc_viewer – Integrated QC data & report viewer for MEEGqc.

Subpackage modules
------------------
- viewer_window    : Main QCViewerWindow (QMainWindow)
- content_panel    : Right-hand content viewer (QStackedWidget)
- timeseries_widget: Interactive pyqtgraph time-series viewer
- file_panel       : Left-hand file explorer (QTreeView)
- annotation_manager: MEEGqc derivative file parser
"""

from .viewer_window import QCViewerWindow

__all__ = ["QCViewerWindow"]

