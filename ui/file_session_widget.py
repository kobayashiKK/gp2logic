"""
Self-contained widget holding one GP file session (song, tracks, mapping, MIDI).
Used as the content of each tab in the main QTabWidget.
"""
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QFileDialog, QGroupBox,
    QDialog, QDialogButtonBox, QLineEdit, QMessageBox,
    QSplitter, QSpinBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject

from core.gp_parser import parse_gp_file, TrackInfo
from core.midi_generator import generate_midi
from core.technique_mapper import (
    KeyswitchMapping, ARTICULATION_IDS, ARTICULATION_LABELS,
)
from core.preset_manager import list_presets, load_preset, save_preset

from ui.keyswitch_editor import KeyswitchTableWidget
from ui.drag_export_widget import DragExportWidget


class ParseWorker(QObject):
    finished = pyqtSignal(object, list)   # (song, [TrackInfo])
    error    = pyqtSignal(str)

    def __init__(self, filepath: str):
        super().__init__()
        self._filepath = filepath

    def run(self):
        try:
            song, tracks = parse_gp_file(self._filepath)
            self.finished.emit(song, tracks)
        except Exception as e:
            self.error.emit(str(e))


class FileSessionWidget(QWidget):
    """One GP file session — encapsulates all per-file state and UI."""

    status_changed = pyqtSignal(str)   # message for the main window status bar
    title_changed  = pyqtSignal(str)   # new tab title (filename or "新規")

    def __init__(self, parent=None):
        super().__init__(parent)

        self._song = None
        self._tracks: list[TrackInfo] = []
        self._mapping  = KeyswitchMapping()
        self._midi_bytes: bytes | None = None
        self._current_filepath: str | None = None
        self._thread: QThread | None = None
        self._worker: ParseWorker | None = None

        # Cached status so the tab can restore it when activated
        self.last_status = "GuitarProファイルを開いてください。"

        self._build_ui()
        self._load_preset_list()
        self._auto_load_first_preset()
        self._emit_status(self.last_status)

    # ──────────────────────────────────────────────────────
    # UI layout
    # ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(6, 6, 6, 6)

        # ── Top bar ──────────────────────────────────────
        top = QHBoxLayout()

        self._open_btn = QPushButton("📂 GuitarProを開く")
        self._open_btn.setFixedHeight(32)
        self._open_btn.clicked.connect(lambda: self.open_file())
        top.addWidget(self._open_btn)

        self._reload_btn = QPushButton("🔄")
        self._reload_btn.setFixedSize(32, 32)
        self._reload_btn.setToolTip("再読込 (Cmd+R)")
        self._reload_btn.setEnabled(False)
        self._reload_btn.clicked.connect(self.reload_file)
        top.addWidget(self._reload_btn)

        self._file_label = QLabel("ファイル未選択")
        self._file_label.setStyleSheet("color: #aaa;")
        top.addWidget(self._file_label, 1)

        top.addWidget(QLabel("トラック:"))
        self._track_combo = QComboBox()
        self._track_combo.setMinimumWidth(180)
        self._track_combo.currentIndexChanged.connect(self._on_track_changed)
        top.addWidget(self._track_combo)

        root.addLayout(top)

        # ── Preset bar ───────────────────────────────────
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
        save_btn.clicked.connect(self.save_preset_dialog)
        preset_bar.addWidget(save_btn)

        preset_bar.addStretch()

        preset_bar.addWidget(QLabel("オクターブ:"))
        self._octave_spin = QSpinBox()
        self._octave_spin.setRange(-3, 3)
        self._octave_spin.setValue(1)
        self._octave_spin.setFixedWidth(52)
        self._octave_spin.valueChanged.connect(self._on_mapping_changed)
        preset_bar.addWidget(self._octave_spin)

        generate_btn = QPushButton("▶ MIDI生成")
        generate_btn.setFixedHeight(30)
        generate_btn.clicked.connect(self._generate_midi)
        preset_bar.addWidget(generate_btn)

        root.addLayout(preset_bar)

        # ── Splitter: keyswitch editor | drag export ──────
        splitter = QSplitter(Qt.Orientation.Vertical)

        ks_group = QGroupBox("キースイッチ設定")
        ks_layout = QVBoxLayout(ks_group)

        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("初期キースイッチ:"))
        self._default_art_combo = QComboBox()
        self._default_art_combo.addItem("— なし —", "")
        for art_id in ARTICULATION_IDS:
            label = ARTICULATION_LABELS.get(art_id, art_id)
            self._default_art_combo.addItem(label, art_id)
        self._default_art_combo.setMinimumWidth(200)
        self._default_art_combo.currentIndexChanged.connect(self._on_mapping_changed)
        default_row.addWidget(self._default_art_combo)
        default_row.addStretch()
        ks_layout.addLayout(default_row)

        self._ks_table = KeyswitchTableWidget()
        self._ks_table.mapping_changed.connect(self._on_mapping_changed)
        ks_layout.addWidget(self._ks_table)

        splitter.addWidget(ks_group)

        export_group = QGroupBox("Logicへエクスポート")
        export_layout = QVBoxLayout(export_group)
        self._drag_widget = DragExportWidget()
        self._drag_widget.export_requested.connect(self._generate_midi)
        export_layout.addWidget(self._drag_widget)
        splitter.addWidget(export_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    # ──────────────────────────────────────────────────────
    # File handling
    # ──────────────────────────────────────────────────────

    def open_file(self, path: str | None = None):
        """Open a GP file.  If *path* is None, show the file dialog."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "GuitarProファイルを開く", "",
                "Guitar Pro Files (*.gp *.gpx *.gp5 *.gp4 *.gp3);;All Files (*)"
            )
        if not path:
            return

        if not os.path.exists(path):
            QMessageBox.warning(self, "ファイルが見つかりません",
                                f"ファイルが存在しません:\n{path}")
            return
        try:
            size = os.path.getsize(path)
            if size == 0:
                raise OSError("ファイルサイズが0です")
            if size < 4096 and path.endswith(".gp"):
                raise OSError(
                    "ファイルが iCloud からまだダウンロードされていない可能性があります。\n"
                    "Finder でファイルを右クリック →「ダウンロード」してから再度開いてください。"
                )
        except OSError as e:
            QMessageBox.warning(self, "ファイルアクセスエラー", str(e))
            return

        self._current_filepath = path
        name = Path(path).name
        self._reload_btn.setEnabled(True)
        self._file_label.setText(name)
        self._file_label.setStyleSheet("")
        self.title_changed.emit(name)
        self._emit_status("ファイルを読み込んでいます…")
        self._start_parse(path)

    def reload_file(self):
        if self._current_filepath:
            self._emit_status("再読込しています…")
            self._start_parse(self._current_filepath)

    def has_file(self) -> bool:
        return self._current_filepath is not None

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
        self._song   = song
        self._tracks = tracks
        self._track_combo.blockSignals(True)
        self._track_combo.clear()
        for t in tracks:
            self._track_combo.addItem(f"{t.index + 1}: {t.name}", t.index)
        self._track_combo.blockSignals(False)
        self._track_combo.setCurrentIndex(0)
        self._on_track_changed(0)
        n_events = sum(len(t.events) for t in tracks)
        self._emit_status(
            f"読込完了: {len(tracks)}トラック, 合計{n_events}ノート"
        )

    def _on_parse_error(self, msg: str):
        QMessageBox.critical(self, "読込エラー",
                             f"ファイルの読み込みに失敗しました:\n{msg}")
        self._emit_status("読込エラー")

    def _on_track_changed(self, idx: int):
        self._midi_bytes = None
        self._drag_widget.set_midi_bytes(None)
        if idx < 0 or idx >= len(self._tracks):
            return
        track = self._tracks[idx]
        arts = {e.articulation_id for e in track.events}
        self._emit_status(
            f"トラック: {track.name} | ノート数: {len(track.events)} | "
            f"検出された奏法: {len(arts)}種"
        )

    # ──────────────────────────────────────────────────────
    # Preset management
    # ──────────────────────────────────────────────────────

    def _auto_load_first_preset(self):
        if self._presets:
            try:
                _, mapping = load_preset(self._presets[0]['path'])
                self._apply_mapping(mapping)
                self._preset_combo.blockSignals(True)
                self._preset_combo.setCurrentIndex(1)
                self._preset_combo.blockSignals(False)
            except Exception:
                pass

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
            self._emit_status(f"プリセット '{name}' を読み込みました。")
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
            self._emit_status(f"プリセット '{name}' を読み込みました。")
        except Exception as e:
            QMessageBox.warning(self, "プリセットエラー", str(e))

    def save_preset_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("プリセットを保存")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("プリセット名:"))
        name_edit = QLineEdit("My Preset")
        layout.addWidget(name_edit)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text().strip() or "My Preset"
            mapping = self._collect_mapping()
            path = save_preset(name, mapping)
            self._load_preset_list()
            self._emit_status(f"プリセット '{name}' を保存しました: {path}")

    def _apply_mapping(self, mapping: KeyswitchMapping):
        self._mapping = mapping
        self._ks_table.set_mapping(mapping)
        default_art = mapping.default_articulation or ""
        self._default_art_combo.blockSignals(True)
        idx = self._default_art_combo.findData(default_art)
        self._default_art_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._default_art_combo.blockSignals(False)
        self._midi_bytes = None
        self._drag_widget.set_midi_bytes(None)

    def _collect_mapping(self) -> KeyswitchMapping:
        mapping = self._ks_table.get_mapping()
        mapping.default_articulation = self._default_art_combo.currentData() or ""
        return mapping

    def _on_mapping_changed(self):
        self._midi_bytes = None
        self._drag_widget.set_midi_bytes(None)

    # ──────────────────────────────────────────────────────
    # MIDI generation
    # ──────────────────────────────────────────────────────

    def _generate_midi(self):
        if not self._tracks:
            QMessageBox.information(self, "情報",
                                    "先にGuitarProファイルを開いてください。")
            return

        track_idx = self._track_combo.currentData()
        if track_idx is None:
            return
        track = self._tracks[track_idx]
        if not track.events:
            QMessageBox.warning(self, "警告",
                                "選択したトラックにノートがありません。")
            return

        mapping = self._collect_mapping()
        tempo = 120.0
        if self._song and hasattr(self._song, 'tempo'):
            tempo = float(self._song.tempo) or 120.0

        pitch_offset = self._octave_spin.value() * 12
        try:
            self._midi_bytes = generate_midi(
                track.events, mapping,
                tempo_bpm=tempo, pitch_offset=pitch_offset,
            )
            self._drag_widget.set_midi_bytes(self._midi_bytes)
            oct_val = self._octave_spin.value()
            oct_str = f"+{oct_val}" if oct_val >= 0 else str(oct_val)
            self._emit_status(
                f"MIDI生成完了 ({len(self._midi_bytes)} bytes, "
                f"オクターブ{oct_str}) — Logicにドラッグしてください。"
            )
        except Exception as e:
            QMessageBox.critical(self, "MIDI生成エラー", str(e))

    # ──────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────

    def _emit_status(self, msg: str):
        self.last_status = msg
        self.status_changed.emit(msg)
