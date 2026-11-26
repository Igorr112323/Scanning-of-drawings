"""Screen 4 — Viewer: rotating 3D preview + STEP/STL export."""

from __future__ import annotations

import math
from typing import Sequence

from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.theme import ACCENT, SECONDARY, TEXT
from core.models import ProfilePoint

_RING_SEGMENTS = 56


class IsoPreview(QWidget):
    """Software-rendered revolved wireframe; drag with the mouse to rotate.

    Deliberately simple (rings + silhouette generators) — no OpenGL, no deps.
    It visualises exactly the geometry that gets exported; it is not a CAD kernel.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile: list[ProfilePoint] = []
        self.yaw = math.radians(-32.0)
        self.pitch = math.radians(24.0)
        self._last_mouse = None
        self.setMinimumSize(360, 320)
        self.setCursor(Qt.OpenHandCursor)

    def set_profile(self, profile: Sequence[ProfilePoint]) -> None:
        self.profile = list(profile)
        self.update()

    def mousePressEvent(self, event) -> None:
        self._last_mouse = event.position()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._last_mouse is None:
            return
        delta = event.position() - self._last_mouse
        self.yaw += delta.x() * 0.012
        self.pitch = max(-1.2, min(1.2, self.pitch + delta.y() * 0.010))
        self._last_mouse = event.position()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._last_mouse = None
        self.setCursor(Qt.OpenHandCursor)

    # ------------------------------------------------------------------
    def _project(self, x: float, y: float, z: float) -> QPointF:
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        # rotate around Y then tilt around X
        x1, z1 = x * cy + z * sy, -x * sy + z * cy
        y1, _z2 = y * cp - z1 * sp, y * sp + z1 * cp
        return QPointF(self.width() / 2.0 + x1, self.height() / 2.0 + 30 - y1)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FAFAFC"))

        if not self.profile:
            painter.setPen(QPen(QColor(SECONDARY), 1.5))
            painter.drawText(self.rect(), Qt.AlignCenter, "Нет геометрии для предпросмотра")
            painter.end()
            return

        xs = [p.x for p in self.profile]
        rs = [p.r for p in self.profile]
        cx = (max(xs) + min(xs)) / 2.0
        scale = 250.0 / max(max(xs) - min(xs), 2.0 * max(rs), 1e-6)

        def world(x: float, r: float, theta: float) -> tuple[float, float, float]:
            return ((x - cx) * scale, r * scale * math.sin(theta), r * scale * math.cos(theta))

        pen_light = QPen(QColor("#C7D3E0"), 1.0)
        pen_major = QPen(QColor(ACCENT), 1.8)

        painter.setPen(pen_light)
        for p in self.profile:
            if p.r <= 0:
                continue
            ring = [self._project(*world(p.x, p.r, 2 * math.pi * i / _RING_SEGMENTS)) for i in range(_RING_SEGMENTS)]
            painter.setPen(pen_light)
            painter.drawPolyline(ring + [ring[0]])

        # silhouette generators: top/bottom outline + a few quadrant generators
        painter.setPen(pen_major)
        half = [(p.x, p.r) for p in self.profile if p.r >= 0]
        for theta in (math.pi / 2, 3 * math.pi / 2, 0.0, math.pi):
            pts = [self._project(*world(x, r, theta)) for x, r in half]
            painter.drawPolyline(pts)

        # revolution axis, dash-dot
        painter.setPen(QPen(QColor("#86868B"), 1.2, Qt.DashDotLine))
        axis_a = self._project((min(xs) - cx - 18) * scale, 0, 0)
        axis_b = self._project((max(xs) - cx + 18) * scale, 0, 0)
        painter.drawLine(axis_a, axis_b)
        painter.end()


class ViewerScreen(QWidget):
    export_step = Signal()
    export_stl = Signal()
    new_drawing = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 56)
        root.setSpacing(22)

        preview_card = QFrame()
        preview_card.setObjectName("Card")
        pl = QVBoxLayout(preview_card)
        pl.setContentsMargins(18, 16, 18, 16)
        pl.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("3D-модель")
        title.setObjectName("CardTitle")
        hint = QLabel("Вращай мышью")
        hint.setObjectName("ScreenSubtitle")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(hint)
        self.preview = IsoPreview()
        pl.addLayout(title_row)
        pl.addWidget(self.preview, 1)

        side = QVBoxLayout()
        side.setSpacing(12)
        side_title = QLabel("Готово")
        side_title.setObjectName("ScreenTitle")
        self.stats = QLabel("")
        self.stats.setObjectName("ScreenSubtitle")
        self.stats.setWordWrap(True)

        self.step_button = QPushButton("Скачать .STEP")
        self.step_button.setObjectName("PrimaryButton")
        self.step_button.setMinimumHeight(54)
        self.step_button.setCursor(Qt.PointingHandCursor)
        self.step_button.clicked.connect(self.export_step)

        self.stl_button = QPushButton("Скачать .STL")
        self.stl_button.setObjectName("SecondaryButton")
        self.stl_button.setMinimumHeight(50)
        self.stl_button.setCursor(Qt.PointingHandCursor)
        self.stl_button.clicked.connect(self.export_stl)

        self.new_button = QPushButton("Новый чертёж")
        self.new_button.setObjectName("GhostButton")
        self.new_button.setCursor(Qt.PointingHandCursor)
        self.new_button.clicked.connect(self.new_drawing)

        disclaimer = QLabel("STEP сохраняет твердотельную B-rep геометрию\n(не конструктивное дерево построения)")
        disclaimer.setObjectName("ScreenSubtitle")
        disclaimer.setWordWrap(True)

        side.addWidget(side_title)
        side.addWidget(self.stats)
        side.addSpacing(6)
        side.addWidget(self.step_button)
        side.addWidget(self.stl_button)
        side.addWidget(self.new_button)
        side.addStretch()
        side.addWidget(disclaimer)

        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setMinimumWidth(280)

        root.addWidget(preview_card, 7)
        root.addWidget(side_widget, 3)

    def set_model(self, profile, volume_mm3: float | None, part_name: str = "Деталь") -> None:
        self.preview.set_profile(profile)
        lines = [f"Деталь: {part_name}", "Тело вращения · 1 вид · масштаб 1:1"]
        if volume_mm3 is not None:
            lines.append(f"Объём: {volume_mm3:,.0f} мм³")
        self.stats.setText("\n".join(lines))
