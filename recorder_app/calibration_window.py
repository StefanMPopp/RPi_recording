"""
calibration_window.py
=====================
Settings → Calibrate camera: finding exposure time, gain and aperture with
the arena, the light and the animals in place.

  Exposure   automatic, or a fixed exposure time and gain. A level bar shows
             how bright the background and the animals are; clipped pixels
             are marked on the preview.
  Speed      how fast the animals move, measured live or from a recording.
             From it: the longest exposure that keeps motion blur small, the
             distance an animal covers between frames, and a bar on the
             preview the length of what an animal covers in one second.
  Aperture   a guided sweep through the f-stops on the lens ring, measuring
             sharpness and evenness at each.

The analysis itself is in calibration.py. Exposure changes reach the camera
at once, so the preview shows them; Apply hands the result to the main
window, which keeps it with the profile, and Cancel restores what was set.
"""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from PyQt6.QtCore    import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui     import QColor, QPainter, QPen, QLinearGradient, QPolygonF, QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QGridLayout, QGroupBox, QScrollArea, QDoubleSpinBox, QRadioButton, QButtonGroup,
    QCheckBox, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QInputDialog, QMessageBox, QProgressDialog, QSizePolicy,
)

import calibration
from calibration import (LiveBackground, SpeedTracker, RecordingReader,
                         detect_animals, measure_levels, measure_aperture,
                         analyze_recording_speed, to_gray)
from constants import (
    APP_NAME, PREVIEW_FPS, PREVIEW_WIDTH,
    CALIBRATION_BACKGROUND_TARGET, CALIBRATION_ANIMAL_TARGET,
    CALIBRATION_BLUR_BUDGET_PX, CALIBRATION_BLUR_FRACTION, CALIBRATION_BLUR_RANGE_PX,
    CALIBRATION_TRAVEL_PER_FRAME,
    CALIBRATION_F_STOPS, CALIBRATION_MAX_VIDEO_S,
)
from main_window import COLOR, PreviewWidget, InfoButton

# Overlay colors, RGB
_CLIPPED_COLOR = (239, 83, 80)       # COLOR["red"]
_CRUSHED_COLOR = (66, 165, 245)
_ANIMAL_COLOR  = (76, 175, 80)       # COLOR["green"]
_BAR_COLOR     = (232, 160, 32)      # COLOR["accent"]
_BAR_TEXT      = (30, 30, 30)

# Gray value -> displayed RGB, with clipped values in their marker colors.
# One lookup does both the gray-to-RGB conversion and the marking.
_CLIP_LUT = np.repeat(np.arange(256, dtype=np.uint8)[:, None, None], 3, axis=2)
_CLIP_LUT[calibration.CLIPPED_HIGH:, 0] = _CLIPPED_COLOR
_CLIP_LUT[:calibration.CLIPPED_LOW + 1, 0] = _CRUSHED_COLOR

# Fewer live movements than this give an unreliable 95th percentile
_MIN_SPEED_STEPS = 50

# Corners must keep at least this fraction of the center's light, and an
# f-stop within this factor of the sharpest corners counts as just as sharp
_MIN_EVENNESS          = 0.85
_SHARPNESS_TOLERANCE   = 1.10


def _colored(text: str, color_key: str) -> str:
    return f"<span style='color:{COLOR[color_key]}'>{text}</span>"


def _in_range(value: float, target: tuple[float, float]) -> bool:
    return target[0] <= value <= target[1]


# =============================================================================
# Level bar — where background and animals sit between black and white
# =============================================================================

class LevelBar(QWidget):
    """
    A black-to-white bar with the target ranges in green and two markers:
    the typical background value above the bar, the typical animal value
    below it. Easier to read at a glance than a histogram: two numbers, and
    whether each is where it should be.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._background: float | None = None
        self._animal: float | None = None

    def set_levels(self, background: float | None, animal: float | None) -> None:
        self._background, self._animal = background, animal
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 10
        bar = QRectF(margin, 22, self.width() - 2 * margin, 18)

        def x_of(value: float) -> float:
            return bar.left() + bar.width() * value / 255.0

        gradient = QLinearGradient(bar.topLeft(), bar.topRight())
        gradient.setColorAt(0.0, QColor(0, 0, 0))
        gradient.setColorAt(1.0, QColor(255, 255, 255))
        painter.fillRect(bar, gradient)
        for low, high in (CALIBRATION_ANIMAL_TARGET, CALIBRATION_BACKGROUND_TARGET):
            zone = QRectF(x_of(low), bar.top(), x_of(high) - x_of(low), bar.height())
            painter.fillRect(zone, QColor(76, 175, 80, 110))
            painter.setPen(QPen(QColor(COLOR["green"]), 1))
            painter.drawRect(zone)

        font = QFont(self.font())
        font.setPointSizeF(8.5)
        painter.setFont(font)
        for value, label, above, target in (
                (self._background, "background", True,  CALIBRATION_BACKGROUND_TARGET),
                (self._animal,     "animals",    False, CALIBRATION_ANIMAL_TARGET)):
            if value is None:
                continue
            color = QColor(COLOR["green"] if _in_range(value, target) else COLOR["amber"])
            x = x_of(value)
            tip_y = bar.top() if above else bar.bottom()
            base_y = tip_y - 7 if above else tip_y + 7
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF([QPointF(x, tip_y), QPointF(x - 5, base_y),
                                           QPointF(x + 5, base_y)]))
            text = f"{label} {value:.0f}"
            text_width = painter.fontMetrics().horizontalAdvance(text)
            text_x = min(max(2.0, x - text_width / 2), self.width() - text_width - 2)
            text_y = base_y - 3 if above else base_y + painter.fontMetrics().ascent() + 1
            painter.setPen(color)
            painter.drawText(QPointF(text_x, text_y), text)
        painter.end()


# =============================================================================
# The window
# =============================================================================

class CalibrationWindow(QDialog):

    frame_received = pyqtSignal(np.ndarray, float)   # camera thread → UI thread

    def __init__(self, parent, camera, sensor_mode, fps: float,
                 px_per_cm: float | None, exposure: dict | None,
                 region: calibration.Region, save_dir: Path):
        super().__init__(parent)
        self.setWindowTitle(f"Calibrate camera — {APP_NAME}")
        self.resize(1450, 900)

        self._camera       = camera
        self._mode         = sensor_mode
        self._fps          = fps
        self._save_dir     = save_dir
        self._initial_exposure = exposure
        self._exposure     = exposure
        self.region        = region or (0.0, 0.0, 1.0, 1.0)
        (self._min_exposure_us, max_exposure_us), (self._min_gain, self._max_gain) = \
            camera.exposure_limits()
        # The camera cannot expose longer than one frame
        self._max_exposure_us = min(max_exposure_us, 1e6 / fps)

        self._live_background = LiveBackground()
        self._speed_tracker: SpeedTracker | None = None
        self._speed_started_s = 0.0
        self._busy = False                 # a measurement owns the preview
        self._frame_count = 0
        self._frame_width = PREVIEW_WIDTH  # of the preview frames
        self._aperture_rows: dict[str, tuple[calibration.ApertureResult, float]] = {}

        # A changed exposure changes the brightness, so the background image
        # is rebuilt — once the value has stopped changing
        self._exposure_debounce = QTimer(self)
        self._exposure_debounce.setSingleShot(True)
        self._exposure_debounce.setInterval(400)
        self._exposure_debounce.timeout.connect(self._apply_manual_exposure)

        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(1000)
        self._speed_timer.timeout.connect(self._show_live_speed)

        self._build_ui(px_per_cm)
        self._set_exposure_controls(exposure)
        self._refresh_planning()

        self.frame_received.connect(self._on_frame)
        self._preview_was_running = camera.preview_running
        camera.set_preview_callback(self._on_camera_frame)
        if not self._preview_was_running:
            camera.start_preview(self._on_camera_frame, PREVIEW_FPS)

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build_ui(self, px_per_cm: float | None) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        preview_column = QVBoxLayout()
        hint = QLabel("Drag the orange frame over the arena floor: brightness and "
                      "animal detection use only what is inside it.")
        hint.setStyleSheet(f"color: {COLOR['text_dim']}; font-size: 12px;")
        hint.setWordWrap(True)
        self._preview = PreviewWidget()
        self._preview.set_crop_overlay(self.region)
        self._preview.crop_dragged.connect(self._on_region_dragged)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {COLOR['text_dim']}; font-size: 12px;")
        preview_column.addWidget(hint)
        preview_column.addWidget(self._preview, stretch=1)
        preview_column.addWidget(self._status_label)
        layout.addLayout(preview_column, stretch=1)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(4, 0, 12, 0)
        panel_layout.setSpacing(10)
        panel_layout.addWidget(self._build_exposure_group())
        panel_layout.addWidget(self._build_speed_group(px_per_cm))
        panel_layout.addWidget(self._build_aperture_group())
        panel_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setFixedWidth(500)

        right_column = QVBoxLayout()
        right_column.addWidget(scroll, stretch=1)
        buttons = QHBoxLayout()
        note = QLabel("Apply keeps the exposure for this session;\n"
                      "File → Save profile stores it.")
        note.setStyleSheet(f"color: {COLOR['text_dim']}; font-size: 11px;")
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("Apply")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        buttons.addWidget(note, stretch=1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        right_column.addLayout(buttons)
        layout.addLayout(right_column)

    def _small_label(self, text: str = "") -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color: {COLOR['text_dim']}; font-size: 12px;")
        label.setWordWrap(True)
        return label

    def _value_label(self) -> QLabel:
        label = QLabel("")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 12px;")
        return label

    def _build_exposure_group(self) -> QGroupBox:
        group = QGroupBox("Exposure")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        layout.setVerticalSpacing(6)

        mode_row = QHBoxLayout()
        self._auto_radio   = QRadioButton("Automatic")
        self._manual_radio = QRadioButton("Fixed")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._auto_radio)
        mode_group.addButton(self._manual_radio)
        self._manual_radio.toggled.connect(self._on_exposure_mode_changed)
        for radio in (self._auto_radio, self._manual_radio):
            # The style sheet's font makes the size hint a little too narrow
            radio.setMinimumWidth(radio.sizeHint().width() + 8)
        mode_row.addWidget(self._auto_radio)
        mode_row.addWidget(self._manual_radio)
        mode_row.addWidget(InfoButton(
            "Automatic exposure adjusts brightness all the time, so\n"
            "tracking thresholds that fit one video may not fit the next.\n"
            "Fixed keeps exposure time, gain and white balance constant.\n\n"
            "Choosing Fixed starts from what automatic exposure is using\n"
            "right now. Then:\n"
            "  1. set the exposure time from the motion blur (Speed below)\n"
            "  2. keep gain at 1: gain amplifies noise along with the image\n"
            "  3. open the aperture or add light until the background\n"
            "     marker is in its green range"
        ))
        mode_row.addStretch()
        layout.addLayout(mode_row, 0, 0, 1, 2)

        self._exposure_spin = QDoubleSpinBox()
        self._exposure_spin.setDecimals(2)
        self._exposure_spin.setRange(self._min_exposure_us / 1000, self._max_exposure_us / 1000)
        self._exposure_spin.setSingleStep(0.1)
        self._exposure_spin.setSuffix(" ms")
        self._exposure_spin.setFixedWidth(110)
        self._exposure_spin.valueChanged.connect(self._on_exposure_value_changed)
        exposure_row = QHBoxLayout()
        exposure_row.addWidget(self._exposure_spin)
        exposure_row.addWidget(self._small_label(
            f"at most {self._max_exposure_us / 1000:.1f} ms at {self._fps:g} fps"))
        exposure_row.addStretch()
        layout.addWidget(self._small_label("Exposure time"), 1, 0)
        layout.addLayout(exposure_row, 1, 1)

        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setDecimals(2)
        self._gain_spin.setRange(self._min_gain, self._max_gain)
        self._gain_spin.setSingleStep(0.1)
        self._gain_spin.setFixedWidth(110)
        self._gain_spin.valueChanged.connect(self._on_exposure_value_changed)
        layout.addWidget(self._small_label("Gain"), 2, 0)
        layout.addWidget(self._gain_spin, 2, 1)

        self._level_bar = LevelBar()
        layout.addWidget(self._level_bar, 3, 0, 1, 2)
        self._levels_label = self._value_label()
        layout.addWidget(self._levels_label, 4, 0, 1, 2)

        self._clip_check = QCheckBox("Mark clipped pixels: red = white, blue = black")
        self._clip_check.setChecked(True)
        layout.addWidget(self._clip_check, 5, 0, 1, 2)
        return group

    def _build_speed_group(self, px_per_cm: float | None) -> QGroupBox:
        group = QGroupBox("Animal speed")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        layout.setVerticalSpacing(6)
        row = 0

        def spin(decimals: int, maximum: float, suffix: str, value: float) -> QDoubleSpinBox:
            box = QDoubleSpinBox()
            box.setDecimals(decimals)
            box.setRange(0.0, maximum)
            box.setSuffix(suffix)
            box.setSpecialValueText("—")
            box.setValue(value)
            box.setFixedWidth(110)
            box.valueChanged.connect(self._refresh_planning)
            return box

        self._scale_spin = spin(1, 99999.0, "", px_per_cm or 0.0)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self._scale_spin)
        scale_row.addWidget(self._small_label(
            f"px/cm at {self._mode.width}×{self._mode.height}"
            + (" (from the main window)" if px_per_cm else " — not set in the main window")))
        layout.addWidget(self._small_label("Scale"), row, 0)
        layout.addLayout(scale_row, row, 1)
        row += 1

        self._body_spin = spin(1, 500.0, " mm", 0.0)
        layout.addWidget(self._small_label("Body length"), row, 0)
        layout.addWidget(self._body_spin, row, 1)
        row += 1

        buttons = QHBoxLayout()
        self._live_button = QPushButton("Measure live")
        self._live_button.clicked.connect(self._on_live_speed_toggled)
        # Keeps its width while it reads "Stop"
        self._live_button.setMinimumWidth(self._live_button.sizeHint().width())
        recording_button = QPushButton("Analyze a recording…")
        recording_button.clicked.connect(self._on_analyze_recording)
        buttons.addWidget(self._live_button)
        buttons.addWidget(recording_button)
        buttons.addWidget(InfoButton(
            "Animals are found as dark blobs that differ from a\n"
            "background image of the arena, so dark things that do\n"
            "not move are never counted. Each blob is matched to the\n"
            "nearest blob 0.1 s earlier; matches that could be\n"
            "mistaken, such as animals touching, are left out.\n\n"
            "Speeds are taken while the animals move, so resting does\n"
            "not pull the numbers down. 95 % means 95 % of the moving\n"
            "time is slower than this.\n\n"
            "Live: let the animals behave normally for a minute or\n"
            "more, then Stop. Recording: the first\n"
            f"{CALIBRATION_MAX_VIDEO_S // 60} minutes of an AVI, MP4 or image stack\n"
            "recorded by this app are analyzed."
        ))
        buttons.addStretch()
        layout.addLayout(buttons, row, 0, 1, 2)
        row += 1

        self._speed_result_label = self._value_label()
        layout.addWidget(self._speed_result_label, row, 0, 1, 2)
        row += 1

        self._speed_spin = spin(1, 10000.0, " mm/s", 0.0)
        layout.addWidget(self._small_label("Plan for"), row, 0)
        plan_row = QHBoxLayout()
        plan_row.addWidget(self._speed_spin)
        plan_row.addWidget(self._small_label("filled in from the 95 % speed; editable"))
        layout.addLayout(plan_row, row, 1)
        row += 1

        self._blur_spin = spin(2, 20.0, " px", CALIBRATION_BLUR_BUDGET_PX)
        self._blur_spin.setSingleStep(0.25)
        blur_row = QHBoxLayout()
        blur_row.addWidget(self._blur_spin)
        blur_row.addWidget(InfoButton(
            "How far an animal may move during one exposure, in\n"
            "recorded pixels. Motion blur smears outlines: animals\n"
            "that touch merge into one blob, legs and antennae fade,\n"
            "and the images a tracker uses to tell individuals apart\n"
            "get less distinct. About 1 px keeps blur invisible;\n"
            "centroid tracking alone tolerates a few pixels.\n\n"
            "With a body length and a scale it is filled in as\n"
            f"{CALIBRATION_BLUR_FRACTION * 100:g} % of the body length, kept within "
            f"{CALIBRATION_BLUR_RANGE_PX[0]:g}–{CALIBRATION_BLUR_RANGE_PX[1]:g} px:\n"
            "larger animals tolerate more blur, but beyond a few\n"
            "pixels it closes the gap between touching animals\n"
            "and fades thin legs whatever the body size.\n"
            "Changing the body length or scale fills it in again."
        ))
        self._blur_note = self._small_label()
        blur_row.addWidget(self._blur_note, stretch=1)
        layout.addWidget(self._small_label("Blur allowed"), row, 0)
        layout.addLayout(blur_row, row, 1)
        row += 1
        self._scale_spin.valueChanged.connect(self._fill_blur_allowance)
        self._body_spin.valueChanged.connect(self._fill_blur_allowance)

        self._suggested_exposure_label = QLabel("—")
        self._suggested_exposure_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        self._use_exposure_button = QPushButton("Use this exposure")
        self._use_exposure_button.clicked.connect(self._on_use_longest_exposure)
        # Keeps its width while it reads "In use ✓"
        self._use_exposure_button.setMinimumWidth(
            self._use_exposure_button.sizeHint().width() + 8)
        exposure_row = QHBoxLayout()
        exposure_row.addWidget(self._suggested_exposure_label)
        exposure_row.addWidget(self._use_exposure_button)
        exposure_row.addStretch()
        layout.addWidget(self._small_label("Exposure time"), row, 0)
        layout.addLayout(exposure_row, row, 1)
        row += 1

        self._exposure_note_label = self._value_label()
        layout.addWidget(self._exposure_note_label, row, 0, 1, 2)
        row += 1

        self._planning_label = self._value_label()
        layout.addWidget(self._planning_label, row, 0, 1, 2)
        row += 1

        self._bar_check = QCheckBox("Show 1 s bar on preview")
        self._bar_check.setChecked(True)
        layout.addWidget(self._bar_check, row, 0, 1, 2)
        return group

    def _build_aperture_group(self) -> QGroupBox:
        group = QGroupBox("Aperture sweep")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        instructions = QLabel(
            "<ol style='margin-left:-20px'>"
            "<li>Lay flat targets with fine black print (text, a printed "
            "checkerboard) on the arena floor: one in the center and one in "
            "each corner of the orange frame. A printed resolution test chart "
            "works too, if it reaches the corners of the frame. Animals are not "
            "needed.</li>"
            "<li>Open the aperture fully (lowest f-number) and focus on the center "
            "target. Focus is most precise when the depth of field is "
            "shallowest. Do not refocus after this.</li>"
            "<li>Set the lens ring to an f-stop, choose the same value below "
            "and click Measure. Exposure is automatic during the measurement, "
            "so each f-stop is compared at the same brightness.</li>"
            "<li>Repeat for each f-stop up to f/8. Then set the ring to the "
            "recommended f-stop.</li></ol>"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet(f"color: {COLOR['text_dim']}; font-size: 12px;")
        layout.addWidget(instructions)

        controls = QHBoxLayout()
        self._f_stop_combo = QComboBox()
        for f_stop in CALIBRATION_F_STOPS:
            self._f_stop_combo.addItem(f"f/{f_stop}", f_stop)
        self._f_stop_combo.setFixedWidth(90)
        self._measure_aperture_button = QPushButton("Measure")
        self._measure_aperture_button.clicked.connect(self._on_measure_aperture)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._on_clear_aperture)
        controls.addWidget(self._f_stop_combo)
        controls.addWidget(self._measure_aperture_button)
        controls.addWidget(clear_button)
        controls.addWidget(InfoButton(
            "Edge: how many pixels a black-to-white edge of the print\n"
            "is spread over. 1 px is perfectly sharp; lower is better.\n"
            "Worst corner is the blurriest of the four corners.\n\n"
            "Evenness: the darkest corner's white as a share of the\n"
            "center's. Wide open, lenses darken toward the corners\n"
            "(vignetting), so one threshold may not fit the whole arena.\n\n"
            "Light: how much more light the f-stop needs than the\n"
            "brightest one measured. Each full stop halves the light,\n"
            "so it must be made up by a longer exposure (more motion\n"
            "blur), more gain (more noise) or brighter lighting.\n\n"
            "Wide open, lenses are soft and vignette; stopped far down,\n"
            "diffraction blurs again. The best f-stop is in between."
        ))
        controls.addStretch()
        layout.addLayout(controls)

        self._aperture_table = QTableWidget(0, 5)
        self._aperture_table.setHorizontalHeaderLabels(
            ["f-stop", "Edge center", "Worst corner", "Evenness", "Light"])
        self._aperture_table.verticalHeader().setVisible(False)
        self._aperture_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._aperture_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        row_height = 22
        self._aperture_table.verticalHeader().setDefaultSectionSize(row_height)
        self._aperture_table.setFixedHeight(
            row_height * len(CALIBRATION_F_STOPS)
            + self._aperture_table.horizontalHeader().sizeHint().height() + 4)
        layout.addWidget(self._aperture_table)

        self._aperture_label = self._value_label()
        layout.addWidget(self._aperture_label)
        return group

    # ── Preview frames ─────────────────────────────────────────────────────────

    def _on_camera_frame(self, frame: np.ndarray) -> None:
        """Camera thread: hand the frame and its sensor time to the UI thread."""
        time_s = self._camera.last_preview_time_s or time.perf_counter()
        self.frame_received.emit(frame, time_s)

    def _on_frame(self, frame: np.ndarray, time_s: float) -> None:
        if self._busy:
            return
        self._frame_count += 1
        self._frame_width = frame.shape[1]
        gray = to_gray(frame)
        self._live_background.add(gray, time_s)
        background = self._live_background.background
        detection = (detect_animals(gray, background, self.region)
                     if background is not None else None)

        if self._speed_tracker is not None and detection is not None:
            self._speed_tracker.add(time_s, detection.blobs)

        # Levels change slowly; every third frame keeps the window responsive
        if self._frame_count % 3 == 0:
            self._show_levels(measure_levels(gray, self.region, detection))
            if self._auto_radio.isChecked():
                self._show_auto_exposure_values()
        self._show_detection_status(detection)
        self._preview.update_frame(self._decorate(frame, gray, detection))

    def _decorate(self, frame: np.ndarray, gray: np.ndarray,
                  detection: calibration.Detection | None) -> np.ndarray:
        """The preview frame with clipped pixels, animals and the speed bar drawn in."""
        mark_clipped = self._clip_check.isChecked()
        if frame.ndim == 2:
            display = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            if mark_clipped:
                display = cv2.LUT(display, _CLIP_LUT)
        else:
            display = np.array(frame[:, :, :3])
            if mark_clipped:
                display[gray >= calibration.CLIPPED_HIGH] = _CLIPPED_COLOR
                display[gray <= calibration.CLIPPED_LOW]  = _CRUSHED_COLOR
        if detection is not None:
            for blob in detection.blobs:
                radius = int(max(4, np.sqrt(blob.area) * 0.9))
                cv2.circle(display, (int(blob.x), int(blob.y)), radius, _ANIMAL_COLOR, 1,
                           cv2.LINE_AA)
        if self._bar_check.isChecked():
            self._draw_speed_bar(display)
        return display

    def _draw_speed_bar(self, display: np.ndarray) -> None:
        """
        A bar as long as an animal at the planned speed travels in one second
        (or the longest of ½, ¼ or ⅒ s that fits), with a tick for each frame
        at the recording frame rate.
        """
        speed = self._speed_spin.value()
        px_per_mm = self._preview_px_per_mm(display.shape[1])
        if speed <= 0 or px_per_mm is None:
            return
        rows, columns = calibration.region_slices(self.region, display.shape)
        room = columns.stop - columns.start - 40
        duration_s = next((duration for duration in (1.0, 0.5, 0.25, 0.1)
                           if speed * duration * px_per_mm <= room), None)
        if duration_s is None:
            return
        length = speed * duration_s * px_per_mm
        left, y = columns.start + 20, rows.stop - 24
        cv2.line(display, (left, y), (int(left + length), y), _BAR_COLOR, 4)

        frame_spacing = speed / self._fps * px_per_mm
        every = 1
        while frame_spacing * every < 6:
            every *= 2
        frame_count = int(duration_s * self._fps / every)
        for tick in range(frame_count + 1):
            x = int(left + tick * every * frame_spacing)
            cv2.line(display, (x, y - 6), (x, y + 6), _BAR_TEXT, 1)

        tick_text = "1 frame" if every == 1 else f"{every} frames"
        cv2.putText(display, f"{speed:g} mm/s: {duration_s:g} s, tick = {tick_text}",
                    (left, y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, _BAR_TEXT, 1, cv2.LINE_AA)

    def _preview_px_per_mm(self, preview_width: int) -> float | None:
        scale = self._scale_spin.value()
        if scale <= 0:
            return None
        return scale / 10 * preview_width / self._mode.width

    def _on_region_dragged(self, x: float, y: float, width: float, height: float) -> None:
        if width < 0.05 or height < 0.05:
            return
        self.region = (x, y, width, height)
        self._preview.set_crop_overlay(self.region)

    # ── Exposure ───────────────────────────────────────────────────────────────

    def _set_exposure_controls(self, exposure: dict | None) -> None:
        for widget in (self._exposure_spin, self._gain_spin, self._manual_radio):
            widget.blockSignals(True)
        if exposure is None:
            self._auto_radio.setChecked(True)
        else:
            self._manual_radio.setChecked(True)
            self._exposure_spin.setValue(exposure["exposure_us"] / 1000)
            self._gain_spin.setValue(exposure["analogue_gain"])
        for widget in (self._exposure_spin, self._gain_spin, self._manual_radio):
            widget.blockSignals(False)
        self._exposure_spin.setEnabled(exposure is not None)
        self._gain_spin.setEnabled(exposure is not None)

    def _show_auto_exposure_values(self) -> None:
        """Show what automatic exposure is doing in the (disabled) fields."""
        metadata = self._camera.last_metadata
        if "ExposureTime" not in metadata:
            return
        for widget, value in ((self._exposure_spin, metadata["ExposureTime"] / 1000),
                              (self._gain_spin, metadata.get("AnalogueGain", 1.0))):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._refresh_planning()

    def _on_exposure_mode_changed(self, manual: bool) -> None:
        if manual:
            # Start from what automatic exposure is using now
            metadata = self._camera.last_metadata
            color_gains = metadata.get("ColourGains")
            self._exposure = {
                "exposure_us":   int(min(self._max_exposure_us,
                                         metadata.get("ExposureTime",
                                                      self._exposure_spin.value() * 1000))),
                "analogue_gain": round(float(metadata.get("AnalogueGain", 1.0)), 2),
                "color_gains":  ([round(float(gain), 3) for gain in color_gains]
                                  if color_gains else None),
            }
        else:
            self._exposure = None
        self._set_exposure_controls(self._exposure)
        self._camera.set_exposure(self._exposure)
        self._live_background.reset()
        self._refresh_planning()

    def _on_exposure_value_changed(self, _value: float) -> None:
        if self._manual_radio.isChecked():
            self._exposure_debounce.start()
            self._refresh_planning()

    def _apply_manual_exposure(self) -> None:
        if not self._manual_radio.isChecked():
            return
        self._exposure = dict(self._exposure or {},
                              exposure_us=int(round(self._exposure_spin.value() * 1000)),
                              analogue_gain=round(self._gain_spin.value(), 2))
        self._camera.set_exposure(self._exposure)
        self._live_background.reset()

    def _current_exposure_s(self) -> float:
        return self._exposure_spin.value() / 1000

    def _show_levels(self, levels: calibration.Levels) -> None:
        self._level_bar.set_levels(levels.background, levels.animal)
        lines = []
        if levels.background is not None:
            low, high = CALIBRATION_BACKGROUND_TARGET
            if levels.background > high:
                verdict = _colored("too bright: little margin before white clips", "amber")
            elif levels.background < low:
                verdict = _colored("too dark: animals stand out less", "amber")
            else:
                verdict = _colored("good", "green")
            lines.append(f"Background {levels.background:.0f} (target {low}–{high}): {verdict}")
        if levels.animal is not None:
            low, high = CALIBRATION_ANIMAL_TARGET
            if levels.animal < low:
                verdict = _colored("nearly black: body detail is lost", "amber")
            elif levels.animal > high:
                verdict = _colored("light: little contrast to the background", "amber")
            else:
                verdict = _colored("good", "green")
            lines.append(f"Animals {levels.animal:.0f} (target {low}–{high}): {verdict}")
        clipped = f"{levels.clipped_pct:.1f} % of the arena is pure white"
        lines.append(_colored(clipped, "red" if levels.clipped_pct >= 1 else
                              "amber" if levels.clipped_pct >= 0.1 else "text_dim"))
        if levels.crushed_pct is not None and levels.crushed_pct >= 1:
            lines.append(_colored(f"{levels.crushed_pct:.0f} % of animal pixels are pure black",
                                  "amber"))
        self._levels_label.setText("<br>".join(lines))

    def _show_detection_status(self, detection: calibration.Detection | None) -> None:
        if detection is None:
            self._status_label.setText(
                f"Learning what the arena looks like: "
                f"{self._live_background.progress * 100:.0f} %. Animals are found "
                f"once it is done, and only while they move."
            )
        elif not detection.blobs:
            self._status_label.setText("No moving animals inside the frame.")
        else:
            count = len(detection.blobs)
            self._status_label.setText(
                f"{count} moving animal{'s' if count != 1 else ''} detected (green circles)."
            )

    # ── Speed ──────────────────────────────────────────────────────────────────

    def _px_per_mm(self) -> float | None:
        """Recorded pixels per mm, or None without a scale."""
        scale = self._scale_spin.value()
        return scale / 10 if scale > 0 else None

    def _fill_blur_allowance(self, *_args) -> None:
        """Blur allowed from the animal's size in pixels, when it is known."""
        px_per_mm = self._px_per_mm()
        body_length = self._body_spin.value()
        if px_per_mm is None or body_length <= 0:
            self._blur_note.setText("")
            return
        body_px = body_length * px_per_mm
        low, high = CALIBRATION_BLUR_RANGE_PX
        blur_px = min(high, max(low, CALIBRATION_BLUR_FRACTION * body_px))
        # Rounded down to the spin box's step
        self._blur_spin.setValue(max(low, math.floor(blur_px * 4) / 4))
        self._blur_note.setText(f"from the body length: animals are {body_px:.0f} px long")

    def _on_live_speed_toggled(self) -> None:
        if self._speed_tracker is not None:
            self._stop_live_speed()
            return
        if self._px_per_mm() is None:
            QMessageBox.information(self, "Scale needed",
                                    "Enter the scale (px/cm) first, so speeds can be "
                                    "given in mm/s.")
            return
        self._speed_tracker = SpeedTracker(
            px_per_mm=self._preview_px_per_mm(self._frame_width))
        self._speed_started_s = time.perf_counter()
        self._live_button.setText("Stop")
        self._speed_timer.start()
        self._show_live_speed()

    def _show_live_speed(self) -> None:
        if self._speed_tracker is None:
            return
        elapsed = time.perf_counter() - self._speed_started_s
        summary = self._speed_tracker.summary()
        text = f"Measuring live: {elapsed:.0f} s, "
        if summary is None:
            text += "no movements measured yet."
        else:
            text += f"{summary.steps} movements. " + self._summary_text(summary)
        self._speed_result_label.setText(text)

    def _stop_live_speed(self) -> None:
        tracker, self._speed_tracker = self._speed_tracker, None
        self._speed_timer.stop()
        self._live_button.setText("Measure live")
        summary = tracker.summary() if tracker is not None else None
        self._show_speed_result("Live", summary)

    def _show_speed_result(self, source: str, summary: calibration.SpeedSummary | None) -> None:
        if summary is None:
            self._speed_result_label.setText(
                _colored(f"{source}: no movements measured. Are animals moving inside "
                         f"the frame, and shown with green circles?", "amber"))
            return
        text = f"{source}: {summary.steps} movements. " + self._summary_text(summary)
        if summary.steps < _MIN_SPEED_STEPS:
            text += "<br>" + _colored("Few movements: measure longer for a reliable value.",
                                      "amber")
        self._speed_result_label.setText(text)
        self._speed_spin.setValue(round(summary.p95_mm_s, 1))

    @staticmethod
    def _summary_text(summary: calibration.SpeedSummary) -> str:
        return (f"<b>95 % {summary.p95_mm_s:.1f} mm/s</b>, "
                f"99 % {summary.p99_mm_s:.1f} mm/s, fastest {summary.max_mm_s:.1f} mm/s.")

    def _on_analyze_recording(self) -> None:
        if self._speed_tracker is not None:
            self._stop_live_speed()
        start_dir = str(self._save_dir) if self._save_dir.exists() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a recording (for an image stack, any of its images)", start_dir,
            "Recordings (*.avi *.mp4 *.tiff *.tif *.png)")
        if not path:
            return
        try:
            reader = RecordingReader(Path(path))
        except Exception as open_error:
            QMessageBox.warning(self, "Cannot read recording", str(open_error))
            return

        px_per_cm = reader.px_per_cm
        if not px_per_cm:
            px_per_cm, ok = QInputDialog.getDouble(
                self, "Scale of this recording",
                f"{reader.name} has no scale in its metadata.\n"
                f"Pixels per cm in the recorded frames:",
                self._scale_spin.value() or 10.0, 0.1, 99999.0, 1)
            if not ok:
                return
        if not reader.fps:
            fps, ok = QInputDialog.getDouble(
                self, "Frame rate of this recording",
                f"The frame rate of {reader.name} is unknown.\nFrames per second:",
                self._fps, 0.1, 1000.0, 1)
            if not ok:
                return
            reader.fps = fps

        latest = {}

        def on_progress(fraction: float, frame: np.ndarray, detection) -> None:
            latest["progress"] = (fraction, frame, detection)

        def analyze(canceled):
            with reader:
                return analyze_recording_speed(reader, px_per_cm, on_progress, canceled)

        def show_progress(dialog: QProgressDialog) -> None:
            if "progress" not in latest:
                return
            fraction, frame, detection = latest.pop("progress")
            dialog.setValue(int(fraction * 100))
            display = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            for blob in detection.blobs:
                cv2.circle(display, (int(blob.x), int(blob.y)),
                           int(max(4, np.sqrt(blob.area) * 0.9)), _ANIMAL_COLOR, 1, cv2.LINE_AA)
            self._preview.update_frame(display)

        try:
            summary = self._run_in_thread(f"Analyzing {reader.name}…", analyze,
                                          cancelable=True, on_poll=show_progress)
        except Exception as analysis_error:
            QMessageBox.warning(self, "Could not analyze recording", str(analysis_error))
            return
        self._show_speed_result(f"{reader.name}", summary)

    def _suggested_exposure_us(self) -> float | None:
        """
        The longest exposure that keeps the blur within the allowance at the
        planned speed, limited to one frame and rounded down to what the
        exposure field shows. None without a speed, scale or allowance.
        """
        speed_px_s = self._speed_spin.value() * (self._px_per_mm() or 0)
        budget = self._blur_spin.value()
        if speed_px_s <= 0 or budget <= 0:
            return None
        exposure_us = min(budget / speed_px_s * 1e6, self._max_exposure_us)
        return max(self._min_exposure_us, math.floor(exposure_us / 10) * 10)

    def _refresh_planning(self, *_args) -> None:
        """What the planned speed means for exposure time and frame rate."""
        speed = self._speed_spin.value()
        px_per_mm = self._px_per_mm()
        if speed <= 0 or px_per_mm is None:
            self._suggested_exposure_label.setText("—")
            self._use_exposure_button.setEnabled(False)
            self._use_exposure_button.setText("Use this exposure")
            self._exposure_note_label.setText("")
            self._planning_label.setText(_colored(
                "Measure or enter a speed (and a scale) to see what it means for "
                "exposure time and frame rate.", "text_dim"))
            return

        speed_px_s = speed * px_per_mm
        budget = self._blur_spin.value()
        suggested_us = self._suggested_exposure_us()
        now_ms = self._exposure_spin.value()
        manual = self._manual_radio.isChecked()

        notes = []
        if suggested_us is None:
            self._suggested_exposure_label.setText("—")
            self._use_exposure_button.setEnabled(False)
            notes.append(_colored("Set the blur allowed above 0.", "text_dim"))
        else:
            in_use = manual and abs(now_ms * 1000 - suggested_us) < 5
            self._suggested_exposure_label.setText(f"{suggested_us / 1000:.2f} ms")
            self._use_exposure_button.setEnabled(not in_use)
            self._use_exposure_button.setText("In use ✓" if in_use else "Use this exposure")
            if budget / speed_px_s * 1e6 > self._max_exposure_us:
                notes.append(_colored(
                    f"The blur would allow {budget / speed_px_s * 1e3:.1f} ms, but one "
                    f"frame at {self._fps:g} fps lasts only "
                    f"{self._max_exposure_us / 1000:.1f} ms.", "text_dim"))
        blur_px = speed_px_s * now_ms / 1000
        notes.append(
            f"Now: {now_ms:.2f} ms ({'fixed' if manual else 'automatic'}) → "
            f"{blur_px:.2f} px blur, "
            + (_colored("within the allowance", "green") if blur_px <= budget
               else _colored("more than allowed", "red")))
        self._exposure_note_label.setText("<br>".join(notes))

        travel_mm = speed / self._fps
        text = (f"Travel between frames at {self._fps:g} fps: {travel_mm:.2f} mm "
                f"({travel_mm * px_per_mm:.1f} px)")
        body_length = self._body_spin.value()
        if body_length > 0:
            body_lengths = travel_mm / body_length
            good, marginal = CALIBRATION_TRAVEL_PER_FRAME
            color = ("green" if body_lengths <= good else
                     "amber" if body_lengths <= marginal else "red")
            text += " = " + _colored(f"{body_lengths:.2f} body lengths", color)
            text += (f"<br>For ≤ {good:g} body length per frame through encounters: "
                     f"<b>≥ {speed / (good * body_length):.1f} fps</b>")
        else:
            text += _colored("<br>Enter the body length to judge this for tracking.",
                             "text_dim")
        self._planning_label.setText(text)

    def _on_use_longest_exposure(self) -> None:
        exposure_us = self._suggested_exposure_us()
        if exposure_us is None:
            return
        if not self._manual_radio.isChecked():
            self._manual_radio.setChecked(True)     # starts from the automatic values
        self._exposure_spin.setValue(exposure_us / 1000)
        self._exposure_debounce.stop()
        self._apply_manual_exposure()
        self._refresh_planning()

    # ── Aperture sweep ─────────────────────────────────────────────────────────

    def _on_measure_aperture(self) -> None:
        f_stop = self._f_stop_combo.currentData()
        if self._speed_tracker is not None:
            self._stop_live_speed()

        region = self.region
        camera = self._camera

        def measure(_canceled):
            # Automatic exposure, so every f-stop is measured at about the
            # same brightness; what it needs for that is the light it costs
            camera.set_exposure(None)
            camera.set_recording_crop(None)
            camera.prepare_for_recording(1)
            self._wait_for_stable_exposure()
            frames = [np.asarray(camera.capture_frame(1)[0], dtype=np.float32)
                      for _ in range(4)]
            metadata = camera.last_metadata
            light = metadata.get("ExposureTime", 1) * metadata.get("AnalogueGain", 1.0)
            # Averaging four frames halves the noise, which would otherwise
            # pass for fine detail
            gray = (sum(frames) / len(frames)).astype(np.uint8)
            return measure_aperture(gray, region), light

        try:
            self._camera.pause_preview()
            result, light = self._run_in_thread(f"Measuring f/{f_stop}…", measure)
        except Exception as measure_error:
            QMessageBox.warning(self, "Could not measure", str(measure_error))
            return
        finally:
            self._camera.set_exposure(self._exposure)
            self._live_background.reset()
            try:
                self._camera.resume_preview()
            except Exception:
                pass
        self._aperture_rows[f_stop] = (result, light)
        self._show_aperture_table()
        # Step to the next f-stop, ready for the next measurement
        index = self._f_stop_combo.currentIndex()
        if index + 1 < self._f_stop_combo.count():
            self._f_stop_combo.setCurrentIndex(index + 1)

    def _wait_for_stable_exposure(self, timeout_s: float = 4.0) -> None:
        """Let automatic exposure settle: exposure × gain steady for 5 frames."""
        deadline = time.perf_counter() + timeout_s
        previous, steady = None, 0
        while time.perf_counter() < deadline and steady < 5:
            self._camera.capture_frame(1, discard=True)
            metadata = self._camera.last_metadata
            current = metadata.get("ExposureTime", 0) * metadata.get("AnalogueGain", 1.0)
            steady = steady + 1 if previous and abs(current - previous) <= 0.02 * previous else 0
            previous = current

    def _on_clear_aperture(self) -> None:
        self._aperture_rows.clear()
        self._f_stop_combo.setCurrentIndex(0)
        self._show_aperture_table()

    def _show_aperture_table(self) -> None:
        rows = sorted(self._aperture_rows.items(), key=lambda item: float(item[0]))
        least_light = min((light for _, (_, light) in rows), default=1.0) or 1.0
        self._aperture_table.setRowCount(len(rows))

        def cell(text: str, color_key: str | None = None) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color_key:
                item.setForeground(QColor(COLOR[color_key]))
            return item

        for row, (f_stop, (result, light)) in enumerate(rows):
            center, corner = result.center_edge_px, result.worst_corner_edge_px
            self._aperture_table.setItem(row, 0, cell(f"f/{f_stop}"))
            self._aperture_table.setItem(row, 1, cell(f"{center:.2f} px" if center else "—"))
            self._aperture_table.setItem(row, 2, cell(f"{corner:.2f} px" if corner else "—"))
            self._aperture_table.setItem(row, 3, cell(
                f"{result.evenness * 100:.0f} %",
                "green" if result.evenness >= _MIN_EVENNESS else "amber"))
            self._aperture_table.setItem(row, 4, cell(f"{light / least_light:.1f}×"))
        self._aperture_label.setText(self._aperture_recommendation(rows))

    @staticmethod
    def _aperture_recommendation(rows) -> str:
        if not rows:
            return ""
        missing = sorted({name for _, (result, _) in rows for name in result.missing_targets})
        complete = [(f_stop, result, light) for f_stop, (result, light) in rows
                    if result.worst_corner_edge_px is not None and result.center_edge_px]
        notes = []
        if missing:
            notes.append(_colored("No target found in: " + ", ".join(missing)
                                  + ". Place one there, inside the orange frame.", "amber"))
        if len(complete) < 2:
            notes.append("Measure at least two f-stops to compare.")
            return "<br>".join(notes)

        sharpest = min(result.worst_corner_edge_px for _, result, _ in complete)
        even = [row for row in complete if row[1].evenness >= _MIN_EVENNESS]
        candidates = [row for row in (even or complete)
                      if row[1].worst_corner_edge_px <= sharpest * _SHARPNESS_TOLERANCE]
        # Of the (nearly) sharpest, the one letting in the most light
        f_stop, result, _light = min(candidates, key=lambda row: row[2])
        best_f_stop = min(complete, key=lambda row: row[1].worst_corner_edge_px)[0]
        if f_stop == best_f_stop:
            text = f"Use <b>f/{f_stop}</b>: sharpest corners"
        else:
            text = (f"Use <b>f/{f_stop}</b>: corners within "
                    f"{(_SHARPNESS_TOLERANCE - 1) * 100:.0f} % of the sharpest (f/{best_f_stop}), "
                    f"with more light")
        text += f", evenness {result.evenness * 100:.0f} %."
        notes.insert(0, _colored(text, "green"))
        if not even:
            notes.append(_colored(
                f"At every f-stop the corners get less than {_MIN_EVENNESS * 100:.0f} % of "
                f"the center's light: make the lighting more even.", "amber"))
        return "<br>".join(notes)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _run_in_thread(self, label: str, function, cancelable: bool = False,
                       on_poll=None):
        """
        Run function(canceled) on a worker thread behind a modal progress
        dialog, keeping the window repainting. `canceled` is a callable the
        function may check. Returns its result or raises its error.
        """
        outcome = {}
        cancel_event = threading.Event()

        def run() -> None:
            try:
                outcome["result"] = function(cancel_event.is_set)
            except BaseException as error:
                outcome["error"] = error

        self._busy = True
        dialog = QProgressDialog(label, "Cancel" if cancelable else None,
                                 0, 100 if cancelable else 0, self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0)
        dialog.show()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                QApplication.processEvents()
                if dialog.wasCanceled():
                    cancel_event.set()
                if on_poll is not None:
                    on_poll(dialog)
                time.sleep(0.03)
        finally:
            dialog.close()
            self._busy = False

        if "error" in outcome:
            raise outcome["error"]
        return outcome["result"]

    @property
    def exposure(self) -> dict | None:
        return self._exposure

    def done(self, result: int) -> None:
        self._speed_timer.stop()
        self._speed_tracker = None
        if self._exposure_debounce.isActive():
            self._exposure_debounce.stop()
            self._apply_manual_exposure()
        if result != QDialog.DialogCode.Accepted:
            self._exposure = self._initial_exposure
            self._camera.set_exposure(self._initial_exposure)
        # Frames stop coming here; the main window takes them back
        self._camera.set_preview_callback(None)
        if not self._preview_was_running:
            self._camera.stop_preview()
        super().done(result)
