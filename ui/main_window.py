"""
Main application window for GP2Logic.
Manages a QTabWidget where each tab is one FileSessionWidget (one GP file).
"""
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QPushButton, QStatusBar,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from ui.file_session_widget import FileSessionWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GP2Logic — GuitarPro → Logic MIDI Converter")
        self.resize(900, 700)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._build_menu()
        self._build_tabs()

        # Start with one empty tab
        self._new_tab()

    # ──────────────────────────────────────────────────────
    # Menu
    # ──────────────────────────────────────────────────────

    def _build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("ファイル")

        open_act = QAction("GuitarProを開く…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._open_in_current_tab)
        file_menu.addAction(open_act)

        new_tab_act = QAction("新規タブ", self)
        new_tab_act.setShortcut("Ctrl+T")
        new_tab_act.triggered.connect(self._new_tab_with_dialog)
        file_menu.addAction(new_tab_act)

        self._reload_act = QAction("再読込", self)
        self._reload_act.setShortcut("Ctrl+R")
        self._reload_act.setEnabled(False)
        self._reload_act.triggered.connect(self._reload_current_tab)
        file_menu.addAction(self._reload_act)

        file_menu.addSeparator()

        close_tab_act = QAction("タブを閉じる", self)
        close_tab_act.setShortcut("Ctrl+W")
        close_tab_act.triggered.connect(self._close_current_tab)
        file_menu.addAction(close_tab_act)

        preset_menu = menu.addMenu("プリセット")
        save_preset_act = QAction("現在のマッピングをプリセットとして保存…", self)
        save_preset_act.triggered.connect(self._save_preset_current_tab)
        preset_menu.addAction(save_preset_act)

    # ──────────────────────────────────────────────────────
    # Tab widget
    # ──────────────────────────────────────────────────────

    def _build_tabs(self):
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # "+" button in the top-right corner
        add_btn = QPushButton("+")
        add_btn.setFixedSize(26, 26)
        add_btn.setToolTip("新規タブ (Ctrl+T)")
        add_btn.clicked.connect(self._new_tab_with_dialog)
        self._tabs.setCornerWidget(add_btn, Qt.Corner.TopRightCorner)

        self.setCentralWidget(self._tabs)

    def _new_tab(self, filepath: str | None = None) -> FileSessionWidget:
        """Create a new FileSessionWidget tab and make it active."""
        widget = FileSessionWidget()
        widget.status_changed.connect(self._on_status)
        widget.title_changed.connect(
            lambda title, w=widget: self._set_tab_title(w, title)
        )
        idx = self._tabs.addTab(widget, "新規")
        self._tabs.setCurrentIndex(idx)

        if filepath:
            widget.open_file(filepath)

        return widget

    def _new_tab_with_dialog(self):
        """Open a new tab and immediately show the GP file dialog."""
        widget = self._new_tab()
        widget.open_file()   # shows file-open dialog

    def _close_tab(self, idx: int):
        """Close the tab at *idx*; keep at least one tab open."""
        if self._tabs.count() > 1:
            self._tabs.removeTab(idx)

    def _close_current_tab(self):
        self._close_tab(self._tabs.currentIndex())

    def _on_tab_changed(self, idx: int):
        """Restore status bar and menu state for the newly active tab."""
        widget = self._tabs.widget(idx)
        if isinstance(widget, FileSessionWidget):
            self._statusbar.showMessage(widget.last_status)
            self._reload_act.setEnabled(widget.has_file())

    def _set_tab_title(self, widget: FileSessionWidget, title: str):
        idx = self._tabs.indexOf(widget)
        if idx >= 0:
            self._tabs.setTabText(idx, title)

    # ──────────────────────────────────────────────────────
    # Delegates to the active tab
    # ──────────────────────────────────────────────────────

    def _current_session(self) -> FileSessionWidget | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, FileSessionWidget) else None

    def _open_in_current_tab(self):
        s = self._current_session()
        if s:
            s.open_file()

    def _reload_current_tab(self):
        s = self._current_session()
        if s:
            s.reload_file()

    def _save_preset_current_tab(self):
        s = self._current_session()
        if s:
            s.save_preset_dialog()

    # ──────────────────────────────────────────────────────
    # Status bar
    # ──────────────────────────────────────────────────────

    def _on_status(self, msg: str):
        """Show status only when it comes from the currently active tab."""
        if self.sender() is self._tabs.currentWidget():
            self._statusbar.showMessage(msg)
