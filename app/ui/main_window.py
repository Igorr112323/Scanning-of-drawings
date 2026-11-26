"""DrawToSTEP main window — floating pill bars, one task per screen."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import theme
from app.ui.screens.processing_screen import ProcessingScreen
from app.ui.screens.upload_screen import UploadScreen
from app.ui.screens.verification_screen import VerificationScreen
from app.ui.screens.viewer_screen import ViewerScreen
from app.ui.widgets.icons import (
    icon_arrow_left,
    icon_cube,
    icon_home,
    icon_more,
    icon_ruler,
    icon_share,
)

from core.cad_builder import build_solid, export_step, export_stl
from core.constraint_solver import solve_constraints
from core.ocr_gost import recognize_dimensions
from core.pdf_parser import parse_pdf
from core.scan_preprocess import preprocess_scan
from core.vectorize import vectorize

_EXPORT_DIR = Path("exports")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DrawToSTEP")
        self.resize(1240, 800)
        self.setMinimumSize(1024, 640)

        self._pipeline_result: dict = {}

        # ------------------------------------------------------------- stack
        self.stack = QStackedWidget()
        self.upload_screen = UploadScreen()
        self.processing_screen = ProcessingScreen()
        self.verification_screen = VerificationScreen()
        self.viewer_screen = ViewerScreen()
        for screen in (self.upload_screen, self.processing_screen,
                       self.verification_screen, self.viewer_screen):
            theme.apply_dot_background(screen)
            self.stack.addWidget(screen)

        # --------------------------------------------------------- top bar
        self.back_button = self._circle_button(icon_arrow_left(), 44)
        self.back_button.clicked.connect(self._go_back)

        self.share_button = self._pill_icon_button(icon_share(), "Скопировать путь к файлу")
        self.share_button.clicked.connect(self._copy_file_path)
        self.more_button = self._pill_icon_button(icon_more(), "Ещё")
        self.more_button.clicked.connect(self._show_more_menu)
        top_pill = QFrame()
        top_pill.setObjectName("PillBar")
        pill_layout = QHBoxLayout(top_pill)
        pill_layout.setContentsMargins(6, 6, 6, 6)
        pill_layout.setSpacing(4)
        pill_layout.addWidget(self.share_button)
        pill_layout.addWidget(self.more_button)

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 18, 20, 0)
        top_layout.addWidget(self.back_button, 0, Qt.AlignLeft | Qt.AlignTop)
        top_layout.addStretch(1)
        top_layout.addWidget(top_pill, 0, Qt.AlignRight | Qt.AlignTop)

        # ------------------------------------------------------ bottom bar
        bottom_pill = QFrame()
        bottom_pill.setObjectName("PillBar")
        bottom_layout = QHBoxLayout(bottom_pill)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(2)
        from PySide6.QtCore import QSize
        self.nav_buttons: dict[str, QToolButton] = {}
        for key, icon, tip in (
            ("upload", icon_home(), "Чертёж"),
            ("verify", icon_ruler(), "Размеры"),
            ("view", icon_cube(), "3D"),
        ):
            btn = QToolButton()
            btn.setObjectName("BottomBarIcon")
            btn.setIcon(icon)
            btn.setIconSize(QSize(30, 30))
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self._navigate_to(k))
            bottom_layout.addWidget(btn)
            self.nav_buttons[key] = btn

        bottom_bar = QWidget()
        bottom_layout_wrap = QHBoxLayout(bottom_bar)
        bottom_layout_wrap.setContentsMargins(0, 0, 0, 22)
        bottom_layout_wrap.addStretch(1)
        bottom_layout_wrap.addWidget(bottom_pill, 0)
        bottom_layout_wrap.addStretch(1)

        # ----------------------------------------------------------- toast
        self.toast = QLabel("", self)
        self.toast.setStyleSheet(
            "background: #1D1D1F; color: white; border-radius: 14px; padding: 8px 16px; font-size: 12px;"
        )
        self.toast.hide()

        # ------------------------------------------------------------ root
        central = QWidget()
        central.setObjectName("Central")
        theme.apply_dot_background(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top_bar)
        layout.addWidget(self.stack, 1)
        layout.addWidget(bottom_bar)
        self.setCentralWidget(central)

        # ---------------------------------------------------------- wiring
        self.upload_screen.file_selected.connect(self._on_file_selected)
        self.processing_screen.finished.connect(self._on_processing_done)
        self.verification_screen.build_requested.connect(self._on_build_requested)
        self.viewer_screen.export_step.connect(lambda: self._export("step"))
        self.viewer_screen.export_stl.connect(lambda: self._export("stl"))
        self.viewer_screen.new_drawing.connect(self._reset_to_upload)

        # scan (raster) support is v1.1 — for now only vector PDFs take this path
        self._tif_note_shown = False

        self._go_to("upload")

    # ------------------------------------------------------------ top bar
    def _circle_button(self, icon, diameter: int) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("BackCircle")
        btn.setIcon(icon)
        from PySide6.QtCore import QSize
        btn.setIconSize(QSize(diameter - 16, diameter - 16))
        btn.setFixedSize(diameter, diameter)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _pill_icon_button(self, icon, tip: str) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("IconPillButton")
        btn.setIcon(icon)
        from PySide6.QtCore import QSize
        btn.setIconSize(QSize(22, 22))
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Открыть пример из data/examples", self._open_examples_folder)
        menu.addAction("О программе", self._about)
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))

    def _open_examples_folder(self) -> None:
        folder = Path(__file__).resolve().parents[1] / "data" / "examples"
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _about(self) -> None:
        QMessageBox.information(
            self, "DrawToSTEP",
            "DrawToSTEP 0.1.0\nОфлайн-конвертер чертежей тел вращения\nв твердотельные STEP/STL-модели.\n\n100% локально · без облака · без отправки данных",
        )

    def _copy_file_path(self) -> None:
        path = self._pipeline_result.get("file_path")
        if path:
            QApplication.clipboard().setText(path)
            self._show_toast("Путь скопирован в буфер")
        else:
            self._show_toast("Файл ещё не выбран")

    def _show_toast(self, text: str) -> None:
        self.toast.setText(text)
        self.toast.adjustSize()
        self.toast.move((self.width() - self.toast.width()) // 2, self.height() - 110)
        self.toast.show()
        QTimer.singleShot(2200, self.toast.hide)

    # --------------------------------------------------------- navigation
    _SCREENS = {"upload": 0, "processing": 1, "verification": 2, "view": 3}

    def _go_to(self, key: str) -> None:
        self.stack.setCurrentIndex(self._SCREENS[key])
        for name, btn in self.nav_buttons.items():
            btn.setChecked(name == key)
        self.back_button.setVisible(key != "upload")

    def _go_back(self) -> None:
        current = self.stack.currentIndex()
        if current == 2:
            self._go_to("upload")
        elif current == 3:
            self._go_to("verification")
        elif current == 1:
            self._go_to("upload")
        else:
            self._go_to("upload")

    def _navigate_to(self, key: str) -> None:
        if key == "verify":
            if "dimensions" not in self._pipeline_result:
                self._show_toast("Сначала открой чертёж")
                return
            self._go_to("verification")
        elif key == "view":
            if "solid_name" not in self._pipeline_result:
                self._show_toast("Сначала собери 3D на экране размеров")
                return
            self._go_to("view")
        else:
            self._go_to("upload")

    def _reset_to_upload(self) -> None:
        self._pipeline_result.clear()
        self._go_to("upload")

    # --------------------------------------------------------- pipeline
    def _on_file_selected(self, path: str) -> None:
        suffix = Path(path).suffix.lower()
        if suffix != ".pdf":
            if not self._tif_note_shown:
                self._tif_note_shown = True
                QMessageBox.information(
                    self, "Сканы — v1.1",
                    "Растровые сканы откроются в v1.1 (OpenCV-конвейер готов, OCR-обвязка в процессе).\n"
                    "Сейчас поддерживается векторный PDF из КОМПАС / AutoCAD.",
                )
            return

        t0 = time.perf_counter()
        try:
            drawing = parse_pdf(path)
            dimensions = recognize_dimensions(drawing)
            scaled_profile, contradictions = solve_constraints(dimensions, drawing.profile)
        except Exception as exc:  # surfaced, never swallowed
            QMessageBox.critical(self, "Не удалось разобрать чертёж", f"{exc}")
            return

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._pipeline_result = {
            "file_path": path,
            "drawing": drawing,
            "dimensions": dimensions,
            "profile": scaled_profile if scaled_profile else drawing.profile,
            "contradictions": contradictions,
            "elapsed_ms": elapsed_ms,
        }

        self.verification_screen.set_data(drawing, dimensions, contradictions)
        self.processing_screen.start(Path(path).name)
        self._go_to("processing")

    def _on_processing_done(self) -> None:
        self._go_to("verification")

    def _on_build_requested(self, confirmed_dimensions) -> None:
        profile = self._pipeline_result.get("profile") or []
        try:
            solid = build_solid(profile, confirmed_dimensions)
            volume = solid.val().Volume()
        except Exception as exc:
            QMessageBox.critical(self, "Не удалось построить 3D", str(exc))
            return

        self._pipeline_result["solid"] = solid
        self._pipeline_result["volume_mm3"] = volume
        self._pipeline_result["solid_name"] = Path(self._pipeline_result.get("file_path", "part")).stem

        part_name = self._pipeline_result["solid_name"]
        self.viewer_screen.set_model(profile, volume, part_name)
        self._go_to("view")
        self._show_toast(f"3D собрана за {self._pipeline_result.get('elapsed_ms', 0):.0f} мс + подтверждение")

    def _export(self, kind: str) -> None:
        solid = self._pipeline_result.get("solid")
        if solid is None:
            self._show_toast("Сначала собери 3D")
            return
        stem = self._pipeline_result.get("solid_name", "drawing_model")
        _EXPORT_DIR.mkdir(exist_ok=True)
        if kind == "step":
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить STEP", str(_EXPORT_DIR / f"{stem}.step"), "STEP (*.step *.stp)")
            if path:
                export_step(solid, path)
                self._show_toast("STEP сохранён")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить STL", str(_EXPORT_DIR / f"{stem}.stl"), "STL (*.stl)")
            if path:
                export_stl(solid, path)
                self._show_toast("STL сохранён")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DrawToSTEP")
    app.setStyleSheet(theme.stylesheet())
    theme.dot_grid_pixmap()  # warm the tile cache
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
