"""Screen 3 — Verification (main screen).

Human-in-the-loop is mandatory: every recognized dimension is listed, every
uncertain one (confidence < 0.85 or unlinked) is highlighted yellow and must
be confirmed or edited by the user before "Подтвердить и собрать 3D" becomes
available. The app never invents a dimension.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.theme import ACCENT, GREEN, SECONDARY, TEXT, YELLOW, YELLOW_BG, RED
from app.ui.widgets.icons import icon_check, icon_warn

from core.models import CONFIDENCE_THRESHOLD, Dimension, Symbol
from core.ocr_gost import parse_dimension_text


# ---------------------------------------------------------------- preview ----

def render_drawing_preview(source_path: str, dimensions: list[Dimension]) -> QPixmap:
    """Render the sheet to a pixmap; uncertain dimensions get a yellow halo."""
    path = Path(source_path)
    highlights: list[tuple[float, float, float, float]] = []  # px rects (x, y, w, h)
    px_per_mm = 150.0 / 25.4

    pixmap: QPixmap | None = None
    if path.suffix.lower() == ".pdf":
        try:
            import fitz
            doc = fitz.open(path)
            page = doc.load_page(0)
            zoom = 150.0 / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pixmap = QPixmap()
            pixmap.loadFromData(pix.tobytes("png"))
            doc.close()
            for dim in dimensions:
                if dim.is_uncertain and dim.anchor is not None:
                    ax, ay = dim.anchor
                    w, h = 34.0, 13.0  # approx halo around the text (mm)
                    highlights.append(((ax - w / 2) * px_per_mm, (ay - h / 2) * px_per_mm,
                                       w * px_per_mm, h * px_per_mm))
        except Exception:
            pixmap = None
    else:
        image = QImage(str(path))
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)

    if pixmap is None:
        pixmap = QPixmap(640, 420)
        pixmap.fill(QColor("#FFFFFF"))
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor("#86868B"), 1.5, Qt.DashLine))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "Предпросмотр недоступен")
        painter.end()
        return pixmap

    if highlights:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        for (x, y, w, h) in highlights:
            painter.fillRect(QRectF(x, y, w, h), QColor(255, 204, 0, 110))
            painter.setPen(QPen(QColor("#E0A800"), 2.4))
            painter.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
        painter.end()
    return pixmap


# ---------------------------------------------------------------- rows -------

class DimensionRow(QFrame):
    confirm_toggled = Signal()

    def __init__(self, dim: Dimension, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dim = dim
        self._confirmed = not dim.is_uncertain  # confident dims are pre-confirmed

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        self.icon.setAlignment(Qt.AlignCenter)

        middle = QVBoxLayout()
        middle.setSpacing(2)
        self.title = QLabel()
        self.title.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TEXT};")
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.caption = QLabel()
        self.caption.setStyleSheet(f"font-size: 11px; color: {SECONDARY};")
        self.caption.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        middle.addWidget(self.title)
        middle.addWidget(self.caption)

        self.editor = QLineEdit()
        self.editor.setFixedWidth(100)
        self.editor.setAlignment(Qt.AlignCenter)

        self.confirm_btn = QPushButton("Подтвердить")
        self.confirm_btn.setCursor(Qt.PointingHandCursor)
        self.confirm_btn.setFixedHeight(34)

        layout.addWidget(self.icon)
        layout.addLayout(middle, 1)
        layout.addWidget(self.editor)
        layout.addWidget(self.confirm_btn)

        self._paint_state()
        self.confirm_btn.clicked.connect(self.toggle_confirm)
        self.editor.textChanged.connect(self._on_edit)

    # ---------------------------------------------------------------------
    def _paint_state(self):
        dim = self.dim
        if dim.is_uncertain:
            self.setStyleSheet(f"DimensionRow {{ background: {YELLOW_BG}; border-radius: 18px; border: 1.5px solid #FFE066; }}")
            self.icon.setPixmap(icon_warn().pixmap(24, 24))
            self.title.setText(f"{dim.raw_text} — проверить")
            link = dim.linked_element_id or "нет привязки"
            self.caption.setText(f"уверенность {dim.confidence:.2f} · {link}")
            self.editor.setVisible(True)
            if self.editor.text() != dim.raw_text:
                self.editor.setText(dim.raw_text)
            self.editor.setStyleSheet("")
            self.confirm_btn.setVisible(True)
        else:
            self.setStyleSheet("DimensionRow { background: #FFFFFF; border-radius: 18px; border: 1px solid rgba(0,0,0,0.05); }")
            self.icon.setPixmap(icon_check().pixmap(22, 22))
            self.title.setText(dim.label())
            self.caption.setText(f"уверенность {dim.confidence:.2f} · привязка: {dim.linked_element_id or '—'}")
            self.editor.setVisible(False)
            self.confirm_btn.setVisible(False)
        self._update_confirm_button()

    def _update_confirm_button(self):
        base = "border-radius: 14px; padding: 0 12px; font-weight: 600; font-size: 13px;"
        if self._confirmed:
            self.confirm_btn.setText("Готово ✓")
            self.confirm_btn.setStyleSheet(f"background: {GREEN}; color: white; {base}")
        else:
            self.confirm_btn.setText("Подтвердить")
            self.confirm_btn.setStyleSheet(f"background: #1D1D1F; color: white; {base}")

    def _on_edit(self, _text: str) -> None:
        # user is typing: any edit un-confirms the row until re-confirmed
        if self._confirmed:
            self._confirmed = False
            self._update_confirm_button()
            self.confirm_toggled.emit()

    def toggle_confirm(self) -> None:
        if not self.dim.is_uncertain:
            return
        if self._confirmed:
            self._confirmed = False
            self._paint_state()
            self.confirm_toggled.emit()
            return
        parsed = parse_dimension_text(self.editor.text())
        if parsed is None:
            self.editor.setStyleSheet("QLineEdit { border: 1.5px solid #FF3B30; background: #FFF2F1; border-radius: 10px; padding: 8px 10px; }")
            self.caption.setText("Не могу распознать — примеры: Ø50 · R12 · 120")
            return
        symbol, value, _conf = parsed
        self.dim = Dimension(
            id=self.dim.id, symbol=symbol, value=value,
            raw_text=self.editor.text().strip(), confidence=1.0,
            linked_element_id=self.dim.linked_element_id,
            is_uncertain=False, anchor=self.dim.anchor,
        )
        self._confirmed = True
        self._paint_state()
        self.confirm_toggled.emit()


    def is_confirmed(self) -> bool:
        return self._confirmed

    def current_dimension(self) -> Dimension:
        return self.dim


# ------------------------------------------------------------ screen ---------

class VerificationScreen(QWidget):
    build_requested = Signal(list)  # list[Dimension], all confirmed

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 56)
        root.setSpacing(22)

        # ---------------- left: drawing preview
        preview_card = QFrame()
        preview_card.setObjectName("Card")
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        pl = QVBoxLayout(preview_card)
        pl.setContentsMargins(18, 16, 18, 16)
        pl.setSpacing(8)
        preview_title = QLabel("Чертёж")
        preview_title.setObjectName("CardTitle")
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: #FAFAFC; border-radius: 16px;")
        self.preview.setMinimumSize(QSize(380, 320))
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        pl.addWidget(preview_title)
        pl.addWidget(self.preview, 1)

        # ---------------- right: dimensions list
        right = QVBoxLayout()
        right.setSpacing(12)

        header = QVBoxLayout()
        title = QLabel("Размеры")
        title.setObjectName("ScreenTitle")
        subtitle = QLabel("Жёлтые размеры нужно подтвердить вручную — чертёж решает, а не программа")
        subtitle.setObjectName("ScreenSubtitle")
        subtitle.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(subtitle)
        right.addLayout(header)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        right.addWidget(self.banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(2, 2, 6, 2)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch()
        scroll.setWidget(self.list_container)
        right.addWidget(scroll, 1)

        self.build_button = QPushButton("Подтвердить и собрать 3D")
        self.build_button.setObjectName("PrimaryButton")
        self.build_button.setCursor(Qt.PointingHandCursor)
        self.build_button.setEnabled(False)
        self.build_button.setMinimumHeight(54)
        self.build_button.clicked.connect(self._emit_build)
        right.addWidget(self.build_button)

        root.addWidget(preview_card, 6)
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setMinimumWidth(430)
        root.addWidget(right_widget, 5)

        self.rows: list[DimensionRow] = []
        self._contradictions: list[tuple[str, str]] = []  # (severity, message)
        self._source_path: str = ""

    # ------------------------------------------------------------------
    def set_data(self, drawing, dimensions: list[Dimension], contradictions=()) -> None:
        self._source_path = drawing.source_path
        self._contradictions = [(c.severity, c.message) for c in contradictions]

        pixmap = render_drawing_preview(drawing.source_path, dimensions)
        self._preview_pixmap = pixmap
        self._refresh_preview()

        # rebuild rows
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = []
        insert_at = 0
        for dim in dimensions:
            row = DimensionRow(dim)
            row.confirm_toggled.connect(self._refresh_cta)
            self.list_layout.insertWidget(insert_at, row)
            self.rows.append(row)
            insert_at += 1

        self._refresh_banner()
        self._refresh_cta()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        pixmap = getattr(self, "_preview_pixmap", None)
        if pixmap is None:
            return
        target = self.preview.size()
        scaled = pixmap.scaled(target.width() - 8, target.height() - 8,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)

    def _refresh_banner(self) -> None:
        errors = [m for s, m in self._contradictions if s == "error"]
        warnings_ = [m for s, m in self._contradictions if s == "warning"]
        if errors:
            self.banner.setText("⚠ Противоречия: " + " · ".join(errors))
            self.banner.setStyleSheet(f"background: #FFEDEB; color: {RED}; border-radius: 14px; padding: 10px 14px; font-size: 12px; font-weight: 600;")
            self.banner.setVisible(True)
        elif warnings_:
            self.banner.setText("ⓘ " + " · ".join(warnings_))
            self.banner.setStyleSheet("background: #FFF8E1; color: #8a6d00; border-radius: 14px; padding: 10px 14px; font-size: 12px;")
            self.banner.setVisible(True)
        else:
            self.banner.setVisible(False)

    def _refresh_cta(self) -> None:
        all_confirmed = all(row.is_confirmed() for row in self.rows)
        has_errors = any(s == "error" for s, _ in self._contradictions)
        unconfirmed = sum(1 for row in self.rows if not row.is_confirmed())
        self.build_button.setEnabled(all_confirmed and not has_errors)
        self.build_button.setText(
            "Подтвердить и собрать 3D" if unconfirmed == 0 and not has_errors
            else (f"Осталось подтвердить: {unconfirmed}" if not has_errors else "Исправь противоречия выше")
        )

    def _emit_build(self) -> None:
        self.build_requested.emit([row.current_dimension() for row in self.rows])

    def dimensions(self) -> list[Dimension]:
        return [row.current_dimension() for row in self.rows]
