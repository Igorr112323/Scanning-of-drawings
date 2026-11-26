"""Screen 1 — Upload: big drop zone for a drawing PDF / scan."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.theme import SECONDARY, TEXT, ACCENT
from app.ui.widgets.icons import icon_document

_ACCEPTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class DropZone(QWidget):
    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(230)
        self._hover = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel()
        icon.setPixmap(icon_document().pixmap(64, 64))
        icon.setAlignment(Qt.AlignCenter)

        title = QLabel("Перетащи чертёж PDF / скан")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {TEXT};")

        subtitle = QLabel("Векторный PDF из КОМПАС / CAD — лучший результат.\nСкан — после проверки размеров вручную.\nТела вращения: валы, фланцы, втулки, кольца.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"font-size: 12px; color: {SECONDARY};")

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(Path(u.toLocalFile()).suffix.lower() in _ACCEPTED for u in urls):
                self._hover = True
                self.update()
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hover = False
        urls = event.mimeData().urls()
        for url in urls:
            path = url.toLocalFile()
            if Path(path).suffix.lower() in _ACCEPTED:
                self.file_dropped.emit(path)
                break
        self.update()

    def paintEvent(self, event) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPen, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(ACCENT if self._hover else "#C7C7CC")
        pen = QPen(color, 2.2, Qt.DashLine)
        pen.setDashPattern([6, 4])
        painter.setPen(pen)
        painter.setBrush(QColor("#FFFFFF" if not self._hover else "#F0F7FF"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 24, 24)
        painter.end()


class UploadScreen(QWidget):
    file_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 40, 48, 60)
        root.setSpacing(18)

        title = QLabel("DrawToSTEP")
        title.setObjectName("ScreenTitle")
        subtitle = QLabel("Старые чертежи деталей вращения → редактируемая 3D-модель .STEP")
        subtitle.setObjectName("ScreenSubtitle")

        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self.file_selected)

        pick = QPushButton("Выбрать файл")
        pick.setObjectName("PrimaryButton")
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(self._pick)

        note = QLabel("100% офлайн: чертёж не покидает вашу машину")
        note.setObjectName("ScreenSubtitle")
        note.setAlignment(Qt.AlignCenter)

        row = QHBoxLayout()
        row.addStretch()
        pick_col = QVBoxLayout()
        pick_col.addWidget(pick)
        pick.setMinimumWidth(340)
        row.addLayout(pick_col)
        row.addStretch()

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addSpacing(8)
        root.addWidget(self.drop_zone)
        root.addLayout(row)
        root.addWidget(note)
        root.addStretch()

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбери чертёж", "",
            "Чертежи (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)",
        )
        if path:
            self.file_selected.emit(path)
