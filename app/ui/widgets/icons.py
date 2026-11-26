"""Minimal line-art icons painted with QPainter (SF Symbols style, black stroke).

No icon font, no asset files, fully offline. Each icon is drawn on a 48x48
canvas with a ~2.4px stroke and round caps — crisp at any size and recolourable.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QColor, QPixmap

_INK = QColor("#1D1D1F")
_ACCENT = QColor("#007AFF")


def _canvas(size: int = 48):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(_INK, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    return pm, p


def _finish(pm: QPixmap, p: QPainter) -> QIcon:
    p.end()
    return QIcon(pm)


def icon_arrow_left() -> QIcon:
    pm, p = _canvas()
    p.drawLine(21, 14, 12, 24)
    p.drawLine(12, 24, 21, 34)
    p.drawLine(13, 24, 37, 24)
    return _finish(pm, p)


def icon_share() -> QIcon:
    pm, p = _canvas()
    p.drawLine(24, 6, 24, 28)
    p.drawLine(15, 15, 24, 6)
    p.drawLine(33, 15, 24, 6)
    p.drawRect(10, 22, 28, 20)
    return _finish(pm, p)


def icon_more() -> QIcon:
    pm, p = _canvas()
    p.setBrush(_INK)
    for x in (11, 24, 37):
        p.drawEllipse(QPointF(x, 24), 2.3, 2.3)
    return _finish(pm, p)


def icon_home() -> QIcon:
    pm, p = _canvas()
    path = QPainterPath(QPointF(8, 26))
    path.lineTo(24, 10)
    path.lineTo(40, 26)
    path.moveTo(13, 24)
    path.lineTo(13, 40)
    path.lineTo(35, 40)
    path.lineTo(35, 24)
    p.drawPath(path)
    return _finish(pm, p)


def icon_ruler() -> QIcon:
    pm, p = _canvas()
    p.translate(20, 20)
    p.rotate(-45)
    p.translate(-20, -20)
    p.drawRoundedRect(QRectF(6, 15, 36, 12), 2.5, 2.5)
    for i, x in enumerate((14, 20, 26, 32, 38)):
        tick = 6 if i % 2 == 0 else 4
        p.drawLine(x, 15, x, 15 + tick)
    return _finish(pm, p)


def icon_cube() -> QIcon:
    pm, p = _canvas()
    # isometric cube outline
    p.drawPolygon([QPointF(24, 6), QPointF(41, 15.5), QPointF(41, 34.5),
                   QPointF(24, 44), QPointF(7, 34.5), QPointF(7, 15.5)])
    p.drawLine(QPointF(7, 15.5), QPointF(24, 25))
    p.drawLine(QPointF(41, 15.5), QPointF(24, 25))
    p.drawLine(QPointF(24, 25), QPointF(24, 44))
    return _finish(pm, p)


def icon_document() -> QIcon:
    pm, p = _canvas()
    path = QPainterPath(QPointF(14, 5))
    path.lineTo(28, 5)
    path.lineTo(36, 13)
    path.lineTo(36, 43)
    path.lineTo(14, 43)
    path.closeSubpath()
    path.moveTo(28, 5)
    path.lineTo(28, 13)
    path.lineTo(36, 13)
    p.drawPath(path)
    return _finish(pm, p)


def icon_check() -> QIcon:
    pm, p = _canvas(32)
    p.setPen(QPen(_ACCENT, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(6, 17, 13, 24)
    p.drawLine(13, 24, 26, 8)
    return _finish(pm, p)


def icon_warn() -> QIcon:
    pm, p = _canvas(32)
    p.setPen(QPen(QColor("#B25000"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolygon([QPointF(16, 4), QPointF(30, 27), QPointF(2, 27)])
    p.drawLine(16, 12, 16, 19)
    p.setBrush(QColor("#B25000"))
    p.drawEllipse(QPointF(16, 23.4), 1.4, 1.4)
    return _finish(pm, p)
