"""
Widget that generates a MIDI file and lets the user drag it into Logic Pro.
"""
import os
import tempfile

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QFileDialog
from PyQt6.QtCore import Qt, QMimeData, QUrl, pyqtSignal
from PyQt6.QtGui import QDrag, QColor, QPalette, QFont


class DragExportWidget(QWidget):
    """
    A large drop-zone-style label that, when dragged, provides
    a temporary MIDI file to the target application (Logic Pro).
    """
    export_requested = pyqtSignal()   # Emitted to ask parent to generate MIDI bytes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._midi_bytes: bytes | None = None
        self._temp_path: str | None = None

        self.setMinimumHeight(80)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        layout = QVBoxLayout(self)

        self._label = QLabel("ここをクリックしてからLogicのピアノロールにドラッグ  ▶▶▶")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        self._label.setFont(font)
        layout.addWidget(self._label)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("MIDIファイルとして保存…")
        save_btn.clicked.connect(self._save_file)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._set_style(ready=False)

    def _set_style(self, ready: bool):
        color = "#1e4a7b" if ready else "#2a2a2a"
        border = "#4fc3f7" if ready else "#555"
        self.setStyleSheet(
            f"DragExportWidget {{ background: {color}; border: 2px dashed {border}; border-radius: 8px; }}"
        )

    def set_midi_bytes(self, data: bytes | None):
        self._midi_bytes = data
        self._set_style(ready=data is not None)
        if data:
            self._label.setText("ここをクリックしてからLogicのピアノロールにドラッグ  ▶▶▶")
        else:
            self._label.setText("MIDIを生成するにはトラックとマッピングを設定してください")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.export_requested.emit()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._midi_bytes is None:
            return

        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".mid", delete=False)
        tmp.write(self._midi_bytes)
        tmp.close()
        self._temp_path = tmp.name

        # Start drag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self._temp_path)])
        drag.setMimeData(mime)

        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(Qt.DropAction.CopyAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def _save_file(self):
        if self._midi_bytes is None:
            self.export_requested.emit()
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "MIDIファイルを保存", "", "MIDI Files (*.mid)"
        )
        if path:
            with open(path, "wb") as f:
                f.write(self._midi_bytes)
