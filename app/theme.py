"""DrawToSTEP design system — iPhone minimalism.

Reference: Apple Freeform / Notes. Light #F5F5F7 background with a dotted
grid, white 24px-radius cards and soft shadows, #007AFF accent, #FFCC00 /
#FFF3B0 highlight for dimensions that need the user's attention.
No sidebars, no dense tables — one task per screen.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPixmap
from PySide6.QtCore import Qt

BG = "#F5F5F7"
CARD = "#FFFFFF"
TEXT = "#1D1D1F"
SECONDARY = "#86868B"
ACCENT = "#007AFF"
ACCENT_PRESSED = "#0062CC"
YELLOW = "#FFCC00"
YELLOW_BG = "#FFF3B0"
GREEN = "#34C759"
RED = "#FF3B30"
SEPARATOR = "#E5E5EA"
DOT = "#D8D8DE"

FONT_STACK = ["Inter", "SF Pro Display", "SF Pro Text", "Segoe UI", "Helvetica Neue", "DejaVu Sans"]

CARD_RADIUS = 24
BUTTON_RADIUS = 16
PILL_RADIUS = 999


@lru_cache(maxsize=1)
def dot_grid_pixmap() -> QPixmap:
    """22x22 tile with a single subtle dot — the Freeform-style sheet grid."""
    tile = QPixmap(22, 22)
    tile.fill(QColor(BG))
    painter = QPainter(tile)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QBrush(QColor(DOT)))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(9, 9, 4, 4)
    painter.end()
    return tile


def apply_dot_background(widget) -> None:
    """Tile the dotted grid over a widget's window background role."""
    from PySide6.QtGui import QPalette
    widget.setAutoFillBackground(True)
    palette = widget.palette()
    palette.setBrush(widget.backgroundRole(), QBrush(dot_grid_pixmap()))
    widget.setPalette(palette)


def app_font(size: int, weight: int = QFont.Normal) -> QFont:
    font = QFont()
    font.setFamilies(FONT_STACK)
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def stylesheet() -> str:
    return f"""
    QWidget {{
        color: {TEXT};
        font-family: {", ".join(FONT_STACK)};
        font-size: 13px;
    }}
    QLabel#ScreenTitle {{
        font-size: 26px; font-weight: 700; color: {TEXT}; letter-spacing: -0.4px;
    }}
    QLabel#ScreenSubtitle {{
        font-size: 13px; color: {SECONDARY};
    }}
    QLabel#CardTitle {{
        font-size: 15px; font-weight: 600; color: {TEXT};
    }}
    QFrame#Card {{
        background: {CARD};
        border-radius: {CARD_RADIUS}px;
        border: 1px solid rgba(0, 0, 0, 0.04);
    }}
    QPushButton#PrimaryButton {{
        background: {ACCENT}; color: white; border: none;
        border-radius: {BUTTON_RADIUS}px; padding: 14px 20px; font-size: 15px; font-weight: 600;
    }}
    QPushButton#PrimaryButton:pressed {{ background: {ACCENT_PRESSED}; }}
    QPushButton#PrimaryButton:disabled {{ background: #C7C7CC; color: #FFFFFF; }}
    QPushButton#SecondaryButton {{
        background: {CARD}; color: {ACCENT}; border: 1.5px solid {SEPARATOR};
        border-radius: {BUTTON_RADIUS}px; padding: 13px 20px; font-size: 15px; font-weight: 600;
    }}
    QPushButton#SecondaryButton:pressed {{ background: #F0F7FF; }}
    QPushButton#GhostButton {{
        background: transparent; color: {SECONDARY}; border: none;
        border-radius: {BUTTON_RADIUS}px; padding: 10px 14px; font-size: 13px; font-weight: 500;
    }}
    QPushButton#GhostButton:pressed {{ background: rgba(0,0,0,0.05); }}
    QToolButton#IconPillButton {{
        background: {CARD}; border: 1px solid rgba(0,0,0,0.06); border-radius: 20px;
        padding: 6px;
    }}
    QToolButton#IconPillButton:pressed {{ background: #ECECF1; }}
    QToolButton#BackCircle {{
        background: {CARD}; border: 1px solid rgba(0,0,0,0.06); border-radius: 22px;
        padding: 6px;
    }}
    QToolButton#BackCircle:pressed {{ background: #ECECF1; }}
    QToolButton#BottomBarIcon {{
        background: transparent; border: none; border-radius: 18px; padding: 8px 14px;
    }}
    QToolButton#BottomBarIcon:hover {{ background: rgba(0,0,0,0.04); }}
    QToolButton#BottomBarIcon:checked {{ background: rgba(0, 122, 255, 0.12); }}
    QFrame#PillBar {{
        background: {CARD}; border-radius: {PILL_RADIUS}px;
        border: 1px solid rgba(0,0,0,0.06);
    }}
    QLineEdit {{
        background: #F2F2F7; border: 1.5px solid transparent; border-radius: 10px;
        padding: 8px 10px; font-size: 15px; selection-background-color: {ACCENT};
    }}
    QLineEdit:focus {{ border: 1.5px solid {ACCENT}; background: white; }}
    QProgressBar {{
        background: #E5E5EA; border: none; border-radius: 4px; height: 8px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px; border: none; }}
    QScrollBar::handle:vertical {{ background: #C7C7CC; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """
