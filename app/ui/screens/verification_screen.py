"""Screen 3 — Verification (main screen).

Human-in-the-loop is mandatory: every recognized dimension is listed, every
uncertain one (confidence < 0.85 or unlinked) is highlighted yellow and must
be confirmed or edited by the user before "Подтвердить и собрать 3D" becomes
available. The app never invents a dimension.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QSize, QPoint
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QKeyEvent
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
from core.scan_linking import confirm_dimension_link, nearest_vector_element


# ---------------------------------------------------------------- preview ----

def render_drawing_preview(source_path: str, dimensions: list[Dimension],
                           marks: list[tuple[float, float]] | None = None,
                           mm_per_px: float = 25.4 / 150.0) -> QPixmap:
    """Render the sheet to a pixmap; uncertain dimensions get a yellow halo.

    ``marks`` are drawing coordinates (mm) of manually linked dimensions;
    ``mm_per_px`` converts them back to image pixels for the overlay.
    """
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
    if marks:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        for mx, my in marks:
            px, py = mx / mm_per_px, my / mm_per_px
            painter.setPen(QPen(QColor("#34C759"), 3.0))
            painter.setBrush(QColor(52, 199, 89, 60))
            painter.drawEllipse(QRectF(px - 16, py - 16, 32, 32))
            painter.drawEllipse(QRectF(px - 3.5, py - 3.5, 7, 7))
        painter.end()
    return pixmap


class PreviewLabel(QLabel):
    """Drawing preview that reports raw clicks in label coordinates."""

    clicked = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.clicked.emit(event.position().toPoint())
        super().mousePressEvent(event)


# ---------------------------------------------------------------- rows -------

class DimensionRow(QFrame):
    confirm_toggled = Signal()
    link_toggled = Signal(object)  # emits self — screen manages single active link mode

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

        self.link_btn = QPushButton("Указать на чертеже")
        self.link_btn.setCursor(Qt.PointingHandCursor)
        self.link_btn.setFixedHeight(34)
        self.link_btn.setToolTip("Режим привязки: кликните по линии на чертеже")
        self._manually_linked = False
        self.link_btn.setVisible(self.dim.is_uncertain)

        layout.addWidget(self.icon)
        layout.addLayout(middle, 1)
        layout.addWidget(self.editor)
        layout.addWidget(self.link_btn)
        layout.addWidget(self.confirm_btn)

        # clicking the row background (not its buttons) toggles link mode
        for w in (self.icon, self.title, self.caption):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._link_mode = False
        self._paint_state()
        self.confirm_btn.clicked.connect(self.toggle_confirm)
        self.editor.textChanged.connect(self._on_edit)
        self.link_btn.clicked.connect(self._toggle_link_mode)

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
            tag = " · вручную" if self._manually_linked else ""
            self.caption.setText(f"уверенность {dim.confidence:.2f} · привязка: {dim.linked_element_id or '—'}{tag}")
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


    def _link_allowed(self) -> bool:
        return self.dim.is_uncertain or self._manually_linked

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._link_allowed() and event.button() == Qt.LeftButton:
            self._toggle_link_mode()
            return
        super().mousePressEvent(event)

    def _toggle_link_mode(self) -> None:
        if not self._link_allowed():
            return
        self.link_toggled.emit(self)

    def enter_link_mode(self) -> None:
        self._link_mode = True
        self.setStyleSheet("DimensionRow { background: #EAF2FF; border-radius: 18px; border: 2px solid #0A84FF; }")
        self.link_btn.setText("Отмена привязки")
        self.link_btn.setStyleSheet(f"background: #0A84FF; color: white; border-radius: 14px; padding: 0 12px; font-weight: 700; font-size: 12px;")
        self.caption.setText("Кликните по линии на чертеже — Esc отменяет")

    def exit_link_mode(self) -> None:
        self._link_mode = False
        self.link_btn.setText("Перепривязать" if self._manually_linked else "Указать на чертеже")
        self.link_btn.setStyleSheet("")
        self._paint_state()

    def link_to(self, element_id: str) -> None:
        """Bind this dimension to a drawing element (manual click-to-link)."""
        self.dim = confirm_dimension_link(self.dim, element_id)
        self._confirmed = True
        self._link_mode = False
        self._manually_linked = True
        self.link_btn.setText("Перепривязать")
        self.link_btn.setVisible(True)
        self._paint_state()
        self.confirm_toggled.emit()

    def is_link_mode(self) -> bool:
        return self._link_mode

    def current_anchor_px(self, mm_per_px: float) -> tuple[float, float] | None:
        if self.dim.anchor is None:
            return None
        return (self.dim.anchor[0] / mm_per_px, self.dim.anchor[1] / mm_per_px)

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
        self.preview = PreviewLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: #FAFAFC; border-radius: 16px;")
        self.preview.setMinimumSize(QSize(380, 320))
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.clicked.connect(self._on_preview_clicked)
        self.link_hint = QLabel("Режим привязки — кликните по линии на чертеже · Esc отменяет")
        self.link_hint.setStyleSheet("background: #EAF2FF; color: #0A84FF; border-radius: 12px; padding: 8px 12px; font-size: 12px; font-weight: 600;")
        self.link_hint.setVisible(False)
        self.link_hint.setWordWrap(True)
        pl.addWidget(preview_title)
        pl.addWidget(self.link_hint)
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
        self._drawing = None
        self._mm_per_px: float = 25.4 / 150.0
        self._marks: list[tuple[float, float]] = []  # mm coords of manually linked dims
        self._linking_row: DimensionRow | None = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.installEventFilter(self)

    # ------------------------------------------------------------------
    def set_data(self, drawing, dimensions: list[Dimension], contradictions=()) -> None:
        self._source_path = drawing.source_path
        self._contradictions = [(c.severity, c.message) for c in contradictions]
        self._drawing = drawing
        self._exit_link_mode()
        self._marks = []
        self._dimensions = list(dimensions)

        # one render to measure the image plane
        probe = render_drawing_preview(drawing.source_path, dimensions)
        if probe is not None and not probe.isNull():
            self._mm_per_px = drawing.page_width / max(1, probe.width())
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
            row.confirm_toggled.connect(self._on_row_confirmed)
            row.link_toggled.connect(self._on_row_link_toggled)
            self.list_layout.insertWidget(insert_at, row)
            self.rows.append(row)
            insert_at += 1

        self._dimensions = list(dimensions)
        self._refresh_banner()
        self._refresh_cta()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self._source_path:
            return
        pixmap = render_drawing_preview(self._source_path,
                                         getattr(self, "_dimensions", []),
                                         marks=self._marks, mm_per_px=self._mm_per_px)
        self._preview_pixmap = pixmap
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

    def _on_row_confirmed(self) -> None:
        self._dimensions = self.dimensions()
        self._refresh_preview()
        self._refresh_cta()

    # ------------------------------------------------- click-to-link ----
    def _on_row_link_toggled(self, row: DimensionRow) -> None:
        if self._linking_row is row:
            self._exit_link_mode()
            return
        self._exit_link_mode()
        self._linking_row = row
        row.enter_link_mode()
        self.link_hint.setVisible(True)
        self.preview.setCursor(Qt.CrossCursor)

    def _exit_link_mode(self) -> None:
        if self._linking_row is not None:
            self._linking_row.exit_link_mode()
        self._linking_row = None
        self.link_hint.setVisible(False)
        self.preview.setCursor(Qt.ArrowCursor)

    def eventFilter(self, watched, event):  # type: ignore[override]
        if event.type() == QKeyEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._exit_link_mode()
            return True
        return super().eventFilter(watched, event)

    def _preview_px_to_mm(self, pos: QPoint) -> tuple[float, float] | None:
        pixmap = getattr(self, "_preview_pixmap", None)
        if pixmap is None or pixmap.isNull():
            return None
        target = self.preview.size()
        scaled = pixmap.size().scaled(target.width() - 8, target.height() - 8,
                                      Qt.KeepAspectRatio)
        ox = (target.width() - scaled.width()) / 2.0
        oy = (target.height() - scaled.height()) / 2.0
        x = pos.x() - ox
        y = pos.y() - oy
        if x < 0 or y < 0 or x > scaled.width() or y > scaled.height():
            return None
        scale = pixmap.width() / max(1, scaled.width())
        px = x * scale
        py = y * scale
        return (px * self._mm_per_px, py * self._mm_per_px)

    def _on_preview_clicked(self, pos: QPoint) -> None:
        row = self._linking_row
        if row is None:
            return
        point = self._preview_px_to_mm(pos)
        if point is None:
            return
        elements = getattr(self._drawing, "elements", []) if self._drawing else []
        target = nearest_vector_element(elements, point[0], point[1], max_dist=15.0)
        if target is None:
            row.caption.setText("Слишком далеко от контура (лимит 15 мм) — кликните точнее")
            row.caption.setStyleSheet(f"font-size: 11px; color: {RED}; font-weight: 600;")
            return
        row.caption.setStyleSheet(f"font-size: 11px; color: {SECONDARY};")
        self._marks.append(point)
        row.link_to(target.id)
        self._exit_link_mode()
        self._dimensions = self.dimensions()
        self._refresh_preview()
        self._refresh_cta()

    def _emit_build(self) -> None:
        self.build_requested.emit([row.current_dimension() for row in self.rows])

    def dimensions(self) -> list[Dimension]:
        rows = getattr(self, "rows", [])
        if rows:
            return [row.current_dimension() for row in rows]
        return list(getattr(self, "_dimensions", []))
