"""
Table widget for editing articulation → MIDI note mappings.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QHeaderView, QAbstractItemView, QSpinBox,
    QDialog, QDialogButtonBox, QLineEdit, QGroupBox, QScrollArea,
    QSizePolicy, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from core.technique_mapper import (
    ARTICULATION_IDS, ARTICULATION_LABELS, KeyswitchMapping, VelocityTrigger,
    midi_note_to_name, note_name_to_midi
)


class NotePickerDialog(QDialog):
    """Small dialog to pick a MIDI note by name or number."""

    def __init__(self, current_note: int = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MIDIノートを選択")
        self.setFixedWidth(300)
        self._note = current_note

        layout = QVBoxLayout(self)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例: C0, C#-1, A-2")
        if current_note is not None:
            self._name_edit.setText(midi_note_to_name(current_note))

        self._num_spin = QSpinBox()
        self._num_spin.setRange(0, 127)
        self._num_spin.setValue(current_note or 0)

        self._name_edit.textChanged.connect(self._on_name_changed)
        self._num_spin.valueChanged.connect(self._on_num_changed)

        layout.addWidget(QLabel("ノート名 (例: C0, C#-1):"))
        layout.addWidget(self._name_edit)
        layout.addWidget(QLabel("MIDI番号 (0–127):"))
        layout.addWidget(self._num_spin)

        none_btn = QPushButton("未設定にする")
        none_btn.clicked.connect(self._set_none)
        layout.addWidget(none_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_name_changed(self, text):
        note = note_name_to_midi(text)
        if note is not None and 0 <= note <= 127:
            self._num_spin.blockSignals(True)
            self._num_spin.setValue(note)
            self._num_spin.blockSignals(False)
            self._note = note

    def _on_num_changed(self, val):
        self._note = val
        self._name_edit.blockSignals(True)
        self._name_edit.setText(midi_note_to_name(val))
        self._name_edit.blockSignals(False)

    def _set_none(self):
        self._note = None
        self.accept()

    def selected_note(self):
        return self._note


COL_ARTICULATION = 0
COL_NOTE_NAME = 1
COL_NOTE_NUM = 2
COL_EDIT = 3


class KeyswitchTableWidget(QWidget):
    """Table for editing articulation → MIDI note mapping."""
    mapping_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mapping = KeyswitchMapping()
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<b>奏法 → キースイッチ マッピング</b>"))
        header_layout.addStretch()
        clear_btn = QPushButton("全クリア")
        clear_btn.clicked.connect(self._clear_all)
        header_layout.addWidget(clear_btn)
        layout.addLayout(header_layout)

        # Table
        self._table = QTableWidget(len(ARTICULATION_IDS), 4)
        self._table.setHorizontalHeaderLabels(["奏法", "ノート名", "MIDI番号", ""])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 70)
        self._table.setColumnWidth(3, 50)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.verticalHeader().setDefaultSectionSize(22)
        layout.addWidget(self._table)

        self._populate_rows()

    def _populate_rows(self):
        self._building = True
        for row, art_id in enumerate(ARTICULATION_IDS):
            label_item = QTableWidgetItem(ARTICULATION_LABELS.get(art_id, art_id))
            label_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            label_item.setData(Qt.ItemDataRole.UserRole, art_id)
            self._table.setItem(row, COL_ARTICULATION, label_item)

            note = self._mapping.get_note(art_id)
            self._set_row_note(row, note)

            edit_btn = QPushButton("…")
            edit_btn.setFixedWidth(40)
            edit_btn.clicked.connect(lambda checked, r=row: self._open_picker(r))
            self._table.setCellWidget(row, COL_EDIT, edit_btn)
        self._building = False

    def _set_row_note(self, row: int, note):
        if note is not None:
            name_item = QTableWidgetItem(midi_note_to_name(note))
            num_item = QTableWidgetItem(str(note))
            name_item.setForeground(QColor("#4fc3f7"))
            num_item.setForeground(QColor("#4fc3f7"))
        else:
            name_item = QTableWidgetItem("—")
            num_item = QTableWidgetItem("—")
            name_item.setForeground(QColor("#666"))
            num_item.setForeground(QColor("#666"))
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        num_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, COL_NOTE_NAME, name_item)
        self._table.setItem(row, COL_NOTE_NUM, num_item)

    def _on_cell_double_clicked(self, row, col):
        self._open_picker(row)

    def _open_picker(self, row: int):
        art_id = self._table.item(row, COL_ARTICULATION).data(Qt.ItemDataRole.UserRole)
        current = self._mapping.get_note(art_id)
        dlg = NotePickerDialog(current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            note = dlg.selected_note()
            self._mapping.set_note(art_id, note)
            self._set_row_note(row, note)
            self.mapping_changed.emit()

    def _clear_all(self):
        for art_id in ARTICULATION_IDS:
            self._mapping.set_note(art_id, None)
        self._populate_rows()
        self.mapping_changed.emit()

    def set_mapping(self, mapping: KeyswitchMapping):
        self._mapping = mapping
        self._populate_rows()

    def get_mapping(self) -> KeyswitchMapping:
        return self._mapping

    def highlight_articulation(self, art_id: str):
        """Highlight the row for a given articulation (called during playback preview)."""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_ARTICULATION)
            if item and item.data(Qt.ItemDataRole.UserRole) == art_id:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                break


class VelocityTriggerWidget(QGroupBox):
    """Editor for velocity-range → articulation triggers."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Velocity トリガー", parent)
        self._triggers: list[VelocityTrigger] = []
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(150)
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.addStretch()
        scroll.setWidget(self._inner)
        layout.addWidget(scroll)

        add_btn = QPushButton("+ トリガーを追加")
        add_btn.clicked.connect(self._add_trigger)
        layout.addWidget(add_btn)

    def set_triggers(self, triggers: list[VelocityTrigger]):
        self._triggers = list(triggers)
        self._rebuild()

    def get_triggers(self) -> list[VelocityTrigger]:
        return list(self._triggers)

    def _rebuild(self):
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, vt in enumerate(self._triggers):
            self._inner_layout.insertWidget(i, self._make_row(i, vt))

    def _make_row(self, idx: int, vt: VelocityTrigger) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)

        min_spin = QSpinBox()
        min_spin.setRange(0, 127)
        min_spin.setValue(vt.min_vel)
        max_spin = QSpinBox()
        max_spin.setRange(0, 127)
        max_spin.setValue(vt.max_vel)

        combo = QComboBox()
        for art_id in ARTICULATION_IDS:
            combo.addItem(ARTICULATION_LABELS.get(art_id, art_id), art_id)
        cur_idx = ARTICULATION_IDS.index(vt.articulation_id) if vt.articulation_id in ARTICULATION_IDS else 0
        combo.setCurrentIndex(cur_idx)

        def on_change():
            self._triggers[idx] = VelocityTrigger(
                min_spin.value(), max_spin.value(),
                combo.currentData()
            )
            self.changed.emit()

        min_spin.valueChanged.connect(on_change)
        max_spin.valueChanged.connect(on_change)
        combo.currentIndexChanged.connect(on_change)

        del_btn = QPushButton("✕")
        del_btn.setFixedWidth(28)
        del_btn.clicked.connect(lambda: self._delete(idx))

        hl.addWidget(QLabel("Vel"))
        hl.addWidget(min_spin)
        hl.addWidget(QLabel("–"))
        hl.addWidget(max_spin)
        hl.addWidget(QLabel("→"))
        hl.addWidget(combo, 1)
        hl.addWidget(del_btn)
        return row

    def _add_trigger(self):
        self._triggers.append(VelocityTrigger(64, 127, "alternate_picked"))
        self._rebuild()
        self.changed.emit()

    def _delete(self, idx: int):
        del self._triggers[idx]
        self._rebuild()
        self.changed.emit()
