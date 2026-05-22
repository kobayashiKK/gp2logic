"""
Main application window for GP2Logic.
"""
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QFileDialog, QSplitter, QGroupBox,
    QStatusBar, QDialog, QDialogButtonBox, QLineEdit, QMessageBox,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QAction

from core.gp_parser import parse_gp_file, TrackInfo
from core.midi_generator import generate_midi
from core.technique_mapper import KeyswitchMapping, ARTICULATION_IDS
from core.preset_manager import list_presets, load_preset, save_preset

from ui.keyswitch_editor import KeyswitchTableWidget, VelocityTriggerWidget
from ui.drag_export_widget import DragExportWidget


class ParseWorker(QObject):
    finished = pyqtSignal(object, list)   # (song, [TrackInfo])
    error = pyqtSignal(str)

    def __init__(self, filepath: str):
        super().__init__()
        self._filepath = filepath

    def run(self):
        try:
            song, tracks = parse_gp_file(self._filepath)
            self.finished.emit(song, tracks)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GP2Logic — GuitarPro → Logic MIDI Converter")
        self.resize(900, 700)

        self._song = None
        self._tracks: list[TrackInfo] = []
        self._mapping = KeyswitchMapping()
        self._midi_bytes: bytes | None = None

        self._build_menu()
        self._build_ui()
        self._load_preset_list()
        self._status("GuitarProファイルを開いてください。")

    # ──────────────────────────────────────────────────────
    # Menu
    # ──────────────────────────────────────────────────────

    def _build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("ファイル")
        open_act = QAction("GuitarProを開く…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._open_file)
        file_menu.addAction(open_act)

        preset_menu = menu.addMenu("プリセット")
        save_preset_act = QAction("現在のマッピングをプリセットとして保存…", self)
        save_preset_act.triggered.connect(self._save_preset_dialog)
        preset_menu.addAction(save_preset_act)

    # ──────────────────────────────────────────────────────
    # UI layout
    # ──────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # Top bar
        top = QHBoxLayout()

        self._open_btn = QPushButton("📂 GuitarProを開く")
        self._open_btn.setFixedHeight(32)
        self._open_btn.clicked.connect(self._open_file)
        top.addWidget(self._open_btn)

        self._file_label = QLabel("ファイル未選択")
        self._file_label.setStyleSheet("color: #aaa;")
        top.addWidget(self._file_label, 1)

        top.addWidget(QLabel("トラック:"))
        self._track_combo = QComboBox()
        self._track_combo.setMinimumWidth(180)
        self._track_combo.currentIndexChanged.connect(self._on_track_changed)
        top.addWidget(self._track_combo)

        root.addLayout(top)

        # Preset bar
        preset_bar = QHBoxLayout()
        preset_bar.addWidget(QLabel("プリセット:"))
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(160)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_bar.addWidget(self._preset_combo)

        load_btn = QPushButton("読込")
        load_btn.setFixedWidth(50)
        load_btn.clicked.connect(self._load_preset_from_file)
        preset_bar.addWidget(load_btn)

        save_btn = QPushButton("保存")
        save_btn.setFixedWidth(50)
        save_btn.clicked.connect(self._save_preset_dialog)
        preset_bar.addWidget(save_btn)

        preset_bar.addStretch()

        generate_btn = QPushButton("▶ MIDI生成")
        generate_btn.setFixedHeight(30)
        generate_btn.clicked.connect(self._generate_midi)
        preset_bar.addWidget(generate_btn)

        root.addLayout(preset_bar)

        # Splitter: keyswitch editor | drag widget
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Keyswitch table + velocity triggers
        ks_group = QGroupBox("キースイッチ設定")
        ks_layout = QVBoxLayout(ks_group)
        self._ks_table = KeyswitchTableWidget()
        self._ks_table.mapping_changed.connect(self._on_mapping_changed)
        ks_layout.addWidget(self._ks_table)

        self._vel_widget = VelocityTriggerWidget()
        self._vel_widget.changed.connect(self._on_mapping_changed)
        ks_layout.addWidget(self._vel_widget)
        splitter.addWidget(ks_group)

        # Drag export
        export_group = QGroupBox("Logicへエクスポート")
        export_layout = QVBoxLayout(export_group)
        self._drag_widget = DragExportWidget()
        self._drag_widget.export_requested.connect(self._generate_midi)
        export_layout.addWidget(self._drag_widget)
        splitter.addWidget(export_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # Status bar
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

    # ──────────────────────────────────────────────────────
    # File handling
    # ──────────────────────────────────────────────────────

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "GuitarProファイルを開く", "",
            "Guitar Pro Files (*.gp *.gpx *.gp5 *.gp4 *.gp3);;All Files (*)"
        )
        if not path:
            return

        # iCloud Drive 上のファイルがローカルに落ちているか確認
        import os
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "ファイルが見つかりません",
                f"ファイルが存在しません:\n{path}"
            )
            return
        try:
            size = os.path.getsize(path)
            if size == 0:
                raise OSError("ファイルサイズが0です")
            # iCloud のプレースホルダーは通常 4KB 未満
            if size < 4096 and path.endswith(".gp"):
                raise OSError(
                    "ファイルが iCloud からまだダウンロードされていない可能性があります。\n"
                    "Finder でファイルを右クリック →「ダウンロード」してから再度開いてください。"
                )
        except OSError as e:
            QMessageBox.warning(self, "ファイルアクセスエラー", str(e))
            return

        self._file_label.setText(Path(path).name)
        self._status("ファイルを読み込んでいます…")
        self._start_parse(path)

    def _start_parse(self, filepath: str):
        self._thread = QThread()
        self._worker = ParseWorker(filepath)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_parse_done)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._on_parse_error)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_parse_done(self, song, tracks):
        self._song = song
        self._tracks = tracks
        self._track_combo.blockSignals(True)
        self._track_combo.clear()
        for t in tracks:
            self._track_combo.addItem(f"{t.index + 1}: {t.name}", t.index)
        self._track_combo.blockSignals(False)
        self._track_combo.setCurrentIndex(0)
        self._on_track_changed(0)
        n_events = sum(len(t.events) for t in tracks)
        self._status(f"読込完了: {len(tracks)}トラック, 合計{n_events}ノート")

    def _on_parse_error(self, msg: str):
        QMessageBox.critical(self, "読込エラー", f"ファイルの読み込みに失敗しました:\n{msg}")
        self._status("読込エラー")

    def _on_track_changed(self, idx: int):
        self._midi_bytes = None
        self._drag_widget.set_midi_bytes(None)
        if idx < 0 or idx >= len(self._tracks):
            return
        track = self._tracks[idx]
        arts = {e.articulation_id for e in track.events}
        self._status(
            f"トラック: {track.name} | ノート数: {len(track.events)} | 検出された奏法: {len(arts)}種"
        )

    # ──────────────────────────────────────────────────────
    # Preset management
    # ──────────────────────────────────────────────────────

    def _load_preset_list(self):
        self._presets = list_presets()
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem("— プリセットを選択 —", None)
        for p in self._presets:
            label = p["name"] + (" (組込)" if p["builtin"] else "")
            self._preset_combo.addItem(label, p["path"])
        self._preset_combo.blockSignals(False)

    def _on_preset_selected(self, idx: int):
        path = self._preset_combo.currentData()
        if path is None:
            return
        try:
            name, mapping = load_preset(path)
            self._apply_mapping(mapping)
            self._status(f"プリセット '{name}' を読み込みました。")
        except Exception as e:
            QMessageBox.warning(self, "プリセットエラー", str(e))

    def _load_preset_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "プリセットを読み込む", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            name, mapping = load_preset(path)
            self._apply_mapping(mapping)
            self._load_preset_list()
            self._status(f"プリセット '{name}' を読み込みました。")
        except Exception as e:
            QMessageBox.warning(self, "プリセットエラー", str(e))

    def _save_preset_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("プリセットを保存")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("プリセット名:"))
        name_edit = QLineEdit("My Preset")
        layout.addWidget(name_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text().strip() or "My Preset"
            mapping = self._collect_mapping()
            path = save_preset(name, mapping)
            self._load_preset_list()
            self._status(f"プリセット '{name}' を保存しました: {path}")

    def _apply_mapping(self, mapping: KeyswitchMapping):
        self._mapping = mapping
        self._ks_table.set_mapping(mapping)
        self._vel_widget.set_triggers(mapping.velocity_triggers)
        self._midi_bytes = None
        self._drag_widget.set_midi_bytes(None)

    def _collect_mapping(self) -> KeyswitchMapping:
        mapping = self._ks_table.get_mapping()
        mapping.velocity_triggers = self._vel_widget.get_triggers()
        return mapping

    def _on_mapping_changed(self):
        self._midi_bytes = None
        self._drag_widget.set_midi_bytes(None)

    # ──────────────────────────────────────────────────────
    # MIDI generation
    # ──────────────────────────────────────────────────────

    def _generate_midi(self):
        if not self._tracks:
            QMessageBox.information(self, "情報", "先にGuitarProファイルを開いてください。")
            return

        track_idx = self._track_combo.currentData()
        if track_idx is None:
            return
        track = self._tracks[track_idx]
        if not track.events:
            QMessageBox.warning(self, "警告", "選択したトラックにノートがありません。")
            return

        mapping = self._collect_mapping()
        tempo = 120.0
        if self._song and hasattr(self._song, 'tempo'):
            tempo = float(self._song.tempo) or 120.0

        try:
            self._midi_bytes = generate_midi(track.events, mapping, tempo_bpm=tempo)
            self._drag_widget.set_midi_bytes(self._midi_bytes)
            self._status(f"MIDI生成完了 ({len(self._midi_bytes)} bytes) — Logicにドラッグしてください。")
        except Exception as e:
            QMessageBox.critical(self, "MIDI生成エラー", str(e))

    # ──────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────

    def _status(self, msg: str):
        self._statusbar.showMessage(msg)
