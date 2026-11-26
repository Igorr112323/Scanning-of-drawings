"""Screen 2 — Processing: clean GOST-style checklist with progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.theme import SECONDARY, GREEN, TEXT, SEPARATOR

_STEPS = [
    "Выравнивание листа",
    "Поиск видов",
    "Чтение размеров",
    "Проверка противоречий",
]


class StepRow(QFrame):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 10)
        layout.setSpacing(14)

        self.dot = QLabel()
        self.dot.setFixedSize(26, 26)
        self.dot.setAlignment(Qt.AlignCenter)

        self.text = QLabel(text)
        self.text.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {SECONDARY};")

        layout.addWidget(self.dot)
        layout.addWidget(self.text, 1)
        self.set_state("pending")

    def set_state(self, state: str) -> None:
        if state == "pending":
            self.dot.setText("")
            self.dot.setStyleSheet(f"background: #E5E5EA; border-radius: 13px; border: 1.5px solid {SEPARATOR};")
            self.text.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {SECONDARY};")
        elif state == "active":
            self.dot.setText("")
            self.dot.setStyleSheet("background: #007AFF; border-radius: 13px; border: 4px solid #BFE0FF;")
            self.text.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TEXT};")
        elif state == "done":
            self.dot.setText("✓")
            self.dot.setStyleSheet(f"background: {GREEN}; border-radius: 13px; color: white; font-size: 15px; font-weight: 700;")
            self.text.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {TEXT};")


class ProcessingScreen(QWidget):
    finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 40, 48, 60)
        root.setSpacing(14)

        title = QLabel("Обработка чертежа")
        title.setObjectName("ScreenTitle")
        self.file_label = QLabel("")
        self.file_label.setObjectName("ScreenSubtitle")

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 22, 28, 22)
        card_layout.setSpacing(2)

        self.rows = [StepRow(step) for step in _STEPS]
        for row in self.rows:
            card_layout.addWidget(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, len(_STEPS) * 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)

        hint = QLabel("Ничего не покидает этот компьютер · размеры без подтверждения не применяются")
        hint.setObjectName("ScreenSubtitle")
        hint.setAlignment(Qt.AlignCenter)

        root.addWidget(title)
        root.addWidget(self.file_label)
        root.addSpacing(4)
        root.addWidget(card)
        root.addWidget(self.progress)
        root.addWidget(hint)
        root.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._ticks = 0
        self._stage = 0
        self._stage_ticks = 0

    def start(self, file_name: str) -> None:
        self.file_label.setText(f"Файл: {Path(file_name).name}")
        for row in self.rows:
            row.set_state("pending")
        self.progress.setValue(0)
        self._ticks = 0
        self._stage = 0
        self._stage_ticks = 0
        self.rows[0].set_state("active")
        self._timer.start()

    def _tick(self) -> None:
        # Simulated staged progress; the actual pipeline (< 1 s) runs in
        # MainWindow before this screen is shown — the checklist shows what
        # was done to the sheet, stage by stage.
        self._ticks += 1
        self._stage_ticks += 1
        self.progress.setValue(min(self.progress.maximum(), self.progress.value() + 6))

        ticks_per_stage = 9
        if self._stage_ticks >= ticks_per_stage:
            self.rows[self._stage].set_state("done")
            self._stage += 1
            self._stage_ticks = 0
            if self._stage >= len(self.rows):
                self._timer.stop()
                self.progress.setValue(self.progress.maximum())
                QTimer.singleShot(350, self.finished.emit)
                return
            self.rows[self._stage].set_state("active")
