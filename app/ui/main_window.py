"""DrawToSTEP main window — floating pill bars, one task per screen."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
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
from core.constraint_solver import estimate_scale, solve_constraints
from core.ocr_gost import recognize_dimensions
from core.pdf_parser import parse_pdf
from core.constraint_solver import scan_diameter_tol_mm, scan_linear_tol_mm
from core.scan_pipeline import _DEFAULT_DPI, parse_scan, read_dpi

_EXPORT_DIR = Path("exports")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class ScanWorker(QThread):
    """Runs the scan pipeline (~6 s of RapidOCR) off the UI thread."""

    done = Signal(object)   # dict compatible with MainWindow._pipeline_result
    failed = Signal(str)

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            dpi = read_dpi(self._path) or _DEFAULT_DPI
            linear_tol = scan_linear_tol_mm(dpi)
            diameter_tol = scan_diameter_tol_mm(dpi)
            drawing = parse_scan(self._path)
            dimensions = recognize_dimensions(drawing)
            scaled_profile, contradictions = solve_constraints(
                dimensions, drawing.profile, bore_diameter=drawing.bore_diameter,
                linear_tol_mm=linear_tol, diameter_tol_mm=diameter_tol)
            warnings = []
            if dpi < 300.0:
                warnings.append("Низкое качество скана — пересканируйте в 300 DPI, "
                                "точность ~3 мм")
            if scaled_profile:
                profile_len = max(p.x for p in scaled_profile) - min(p.x for p in scaled_profile)
                confident_linear = [d.value for d in dimensions
                                    if d.symbol.name == "LINEAR" and not d.is_uncertain and d.value > 0]
                if confident_linear and abs(max(confident_linear) - profile_len) > linear_tol:
                    warnings.append(
                        f"Расхождение напечатанной и измеренной длины "
                        f"{abs(max(confident_linear) - profile_len):.1f} мм — "
                        f"пересканируйте в 300 DPI")
            self.done.emit({
                "file_path": self._path,
                "drawing": drawing,
                "scale": estimate_scale(dimensions, drawing.profile,
                                        linear_tol_mm=linear_tol),
                "bore_diameter": drawing.bore_diameter,
                "dimensions": dimensions,
                "profile": scaled_profile if scaled_profile else drawing.profile,
                "contradictions": contradictions,
                "quality_warning": " · ".join(warnings) if warnings else None,
                "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
            })
        except Exception as exc:  # surfaced to the user, never swallowed
            self.failed.emit(str(exc))


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

        self._scan_worker: ScanWorker | None = None
        self._scan_nav_pending = False

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
        if suffix in _IMAGE_SUFFIXES:
            if self._scan_worker is not None:
                QMessageBox.information(self, "Подождите", "Скан ещё обрабатывается.")
                return
            self._pipeline_result = {}
            self._scan_nav_pending = False
            self.processing_screen.start(Path(path).name)
            self._go_to("processing")
            self._scan_worker = ScanWorker(path, self)
            self._scan_worker.done.connect(self._on_scan_ready)
            self._scan_worker.failed.connect(self._on_scan_failed)
            self._scan_worker.start()
            return
        if suffix != ".pdf":
            QMessageBox.warning(self, "Формат не поддерживается",
                                f"Неподдерживаемое расширение: {suffix or '(без расширения)'}\n"
                                "Ожидается PDF (КОМПАС / AutoCAD) или изображение скана.")
            return

        t0 = time.perf_counter()
        try:
            drawing = parse_pdf(path)
            dimensions = recognize_dimensions(drawing)
            scaled_profile, contradictions = solve_constraints(
                dimensions, drawing.profile, bore_diameter=drawing.bore_diameter)
        except Exception as exc:  # surfaced, never swallowed
            QMessageBox.critical(self, "Не удалось разобрать чертёж", f"{exc}")
            return

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._pipeline_result = {
            "file_path": path,
            "drawing": drawing,
            "scale": estimate_scale(dimensions, drawing.profile),
            "bore_diameter": drawing.bore_diameter,
            "dimensions": dimensions,
            "profile": scaled_profile if scaled_profile else drawing.profile,
            "contradictions": contradictions,
            "elapsed_ms": elapsed_ms,
        }

        self.verification_screen.set_data(drawing, dimensions, contradictions)
        self.verification_screen.set_quality_warning(None)
        self.processing_screen.start(Path(path).name)
        self._go_to("processing")

    def _on_processing_done(self) -> None:
        if self._scan_worker is not None:
            # OCR is still running — navigate when the worker finishes
            self._scan_nav_pending = True
            return
        self._go_to("verification")

    def _on_scan_ready(self, result: dict) -> None:
        self._pipeline_result = result
        self._scan_worker = None
        self.verification_screen.set_data(result["drawing"], result["dimensions"],
                                          result["contradictions"])
        self.verification_screen.set_quality_warning(result.get("quality_warning"))
        if self._scan_nav_pending or self.stack.currentIndex() == self._SCREENS["processing"]:
            self._go_to("verification")
        self._scan_nav_pending = False

    def _on_scan_failed(self, message: str) -> None:
        self._scan_worker = None
        self._scan_nav_pending = False
        QMessageBox.critical(self, "Не удалось разобрать скан", message)
        self._go_to("upload")

    def _on_build_requested(self, confirmed_dimensions) -> None:
        profile = self._pipeline_result.get("profile") or []
        bore = self._pipeline_result.get("bore_diameter")
        bore_true = bore * self._pipeline_result.get("scale", 1.0) if bore else None
        try:
            solid = build_solid(profile, confirmed_dimensions, bore_diameter=bore_true)
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
