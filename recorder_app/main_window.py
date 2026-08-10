"""
main_window.py
==============
Main application window for the RPi Recorder.

Layout (setup mode):
┌─────────────────────┬──────────────────────────────────────┐
│                     │  Recording settings                  │
│   Preview widget    │  ─────────────────────────────────── │
│   (with zoom)       │  Metadata                            │
│                     │  ─────────────────────────────────── │
│                     │  Save / Load profile                 │
├─────────────────────┴──────────────────────────────────────┤
│  [ ▶ Start recording ]        status bar                   │
└────────────────────────────────────────────────────────────┘

During recording the right panel switches to a live status view.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore    import Qt, QTimer, pyqtSignal, QThread, QPoint
from PyQt6.QtGui     import QImage, QPixmap, QFont, QColor, QPalette, QAction, QCursor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QGridLayout, QSplitter,
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QToolTip, QStatusBar, QMenuBar,
    QGroupBox, QSizePolicy, QFrame, QScrollArea, QTextEdit, QStyle,
)

import numpy as np

from constants  import (
    APP_NAME, APP_VERSION,
    PREVIEW_WIDTH, PREVIEW_HEIGHT,
    OUTPUT_FORMATS, METADATA_DEFAULTS,
    COLOUR_MODES, DEFAULT_COLOUR_MODE,
)
from config     import load_app_config, save_app_config, load_profile, save_profile, default_profile
from benchmark  import (
    get_free_space_gb, compute_headroom, compute_max_record_time_s,
    estimate_file_size_per_minute_gb,
)
from camera     import make_camera, SensorMode


# =============================================================================
# Colour palette  (dark, instrument-style)
# =============================================================================
# Inspired by oscilloscope / scientific instrument UIs:
# near-black background, cool grey panels, amber accent for live data.

COLOUR = {
    "bg":           "#1A1D21",   # main window background
    "panel":        "#22262C",   # panel / groupbox background
    "border":       "#353A42",   # subtle borders
    "text":         "#D8DCE3",   # primary text
    "text_dim":     "#7A8190",   # labels, units
    "accent":       "#E8A020",   # amber — live recording indicator, headings
    "green":        "#4CAF50",
    "amber":        "#FFA726",
    "red":          "#EF5350",
    "button_start": "#2E7D32",   # start button
    "button_stop":  "#B71C1C",   # stop button
}

STYLE_SHEET = f"""
    QMainWindow, QWidget {{
        background-color: {COLOUR["bg"]};
        color: {COLOUR["text"]};
        font-family: "DejaVu Sans", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QGroupBox {{
        background-color: {COLOUR["panel"]};
        border: 1px solid {COLOUR["border"]};
        border-radius: 6px;
        margin-top: 10px;
        padding: 8px;
        font-size: 11px;
        color: {COLOUR["text_dim"]};
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background-color: {COLOUR["bg"]};
        border: 1px solid {COLOUR["border"]};
        border-radius: 4px;
        padding: 4px 8px;
        color: {COLOUR["text"]};
        selection-background-color: {COLOUR["accent"]};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        background-color: #1B1E23;
        color: #4A4F58;
        border: 1px dashed {COLOUR["border"]};
    }}
    QComboBox::drop-down {{ border: none; }}
    QPushButton {{
        background-color: {COLOUR["panel"]};
        border: 1px solid {COLOUR["border"]};
        border-radius: 4px;
        padding: 6px 14px;
        color: {COLOUR["text"]};
    }}
    QPushButton:hover  {{ border-color: {COLOUR["accent"]}; }}
    QPushButton:pressed {{ background-color: {COLOUR["border"]}; }}
    QLabel {{ background: transparent; }}
    QSplitter::handle {{ background-color: {COLOUR["border"]}; width: 1px; }}
    QScrollArea {{ border: none; }}
    QStatusBar {{ background-color: {COLOUR["panel"]}; color: {COLOUR["text_dim"]}; }}
    QMenuBar {{
        background-color: {COLOUR["panel"]};
        border-bottom: 1px solid {COLOUR["border"]};
    }}
    QMenuBar::item:selected {{ background-color: {COLOUR["border"]}; }}
    QMenu {{
        background-color: {COLOUR["panel"]};
        border: 1px solid {COLOUR["border"]};
    }}
    QMenu::item:selected {{ background-color: {COLOUR["border"]}; }}
"""



# =============================================================================
# Monospace popup — used as a custom tooltip for tables that need fixed-width
# =============================================================================

class MonospacePopup(QFrame):
    """
    A frameless floating window that displays monospaced text.
    Used instead of QToolTip so we can force a monospace font,
    which is required for the format comparison table to align correctly.
    Closes when the mouse leaves the triggering widget.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #2A2F38;
                border: 1px solid {COLOUR['accent']};
                border-radius: 4px;
            }}
            QLabel {{
                color: {COLOUR['text']};
                font-family: "DejaVu Sans Mono", "Courier New", monospace;
                font-size: 12px;
                padding: 10px 14px;
            }}
        """)
        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    def show_text(self, text: str, anchor_global: QPoint) -> None:
        """
        Display text with the popup's top-right corner at anchor_global.
        anchor_global should be the bottom-right corner of the triggering
        widget, so the popup opens leftward and below — never under the
        cursor, which would cause hover flicker.
        """
        self._label.setText(text)
        self.adjustSize()

        screen        = QApplication.primaryScreen().availableGeometry()
        popup_width   = self.width()
        popup_height  = self.height()

        # Open leftward from the anchor
        x = anchor_global.x() - popup_width
        x = max(screen.left() + 4, min(x, screen.right() - popup_width - 4))

        # Open downward; flip above the anchor if it would run off the bottom
        y = anchor_global.y() + 6
        if y + popup_height > screen.bottom():
            y = max(screen.top() + 4, anchor_global.y() - popup_height - 6)

        self.move(x, y)
        self.show()
        self.raise_()


class InfoButton(QLabel):
    """
    A small blue circular 'i' button that shows a MonospacePopup on hover.

    The circle is drawn with CSS rather than using the ⓘ unicode glyph,
    because that glyph is missing from many Linux system fonts and renders
    as an empty box.
    """

    _DIAMETER = 17

    def __init__(self, popup_text: str = "", parent=None):
        super().__init__("i", parent)
        self._popup_text = popup_text
        self._popup      = MonospacePopup()

        self.setFixedSize(self._DIAMETER, self._DIAMETER)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: #2C5F8D;
                color: #CFE4F7;
                border: 1px solid #4A90D9;
                border-radius: {self._DIAMETER // 2}px;
                font-family: "DejaVu Serif", Georgia, serif;
                font-size: 11px;
                font-weight: bold;
                font-style: italic;
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_text(self, text: str) -> None:
        self._popup_text = text

    def enterEvent(self, event) -> None:
        if self._popup_text:
            # Anchor = bottom-right corner of the button, in screen coordinates
            anchor = self.mapToGlobal(QPoint(self.width(), self.height()))
            self._popup.show_text(self._popup_text, anchor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._popup.hide()
        super().leaveEvent(event)


# =============================================================================
# Preview widget — displays camera frames, handles ctrl+scroll zoom
# =============================================================================

class PreviewWidget(QLabel):
    """
    Displays numpy frames from the camera preview stream.
    Supports ctrl+scroll zoom centred on the cursor.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background-color: #0A0C0E; border: 1px solid {COLOUR['border']}; border-radius: 4px;")
        self.setText("No camera signal")

        self._zoom_factor      = 1.0
        self._zoom_origin_x    = 0.5   # fractional centre of zoom (0–1)
        self._zoom_origin_y    = 0.5
        self._current_frame: np.ndarray | None = None

    # ── Frame ingestion ────────────────────────────────────────────────────────

    def update_frame(self, frame_array: np.ndarray) -> None:
        """Receive a new RGB numpy frame and render it with current zoom."""
        self._current_frame = frame_array
        self._render()

    def _render(self) -> None:
        if self._current_frame is None:
            return

        frame = self._current_frame
        frame_height, frame_width = frame.shape[:2]

        if self._zoom_factor > 1.0:
            # Crop to the zoomed region centred on zoom origin
            crop_w = int(frame_width  / self._zoom_factor)
            crop_h = int(frame_height / self._zoom_factor)
            x0 = int(self._zoom_origin_x * frame_width  - crop_w / 2)
            y0 = int(self._zoom_origin_y * frame_height - crop_h / 2)
            x0 = max(0, min(x0, frame_width  - crop_w))
            y0 = max(0, min(y0, frame_height - crop_h))
            frame = frame[y0:y0 + crop_h, x0:x0 + crop_w]

        # Normalise to RGB — picamera2 may deliver greyscale (2D) or RGBA (4ch)
        if frame.ndim == 2:
            # Greyscale → stack to RGB
            frame = np.stack([frame, frame, frame], axis=2)
        elif frame.shape[2] == 4:
            # RGBA → drop alpha channel
            frame = frame[:, :, :3]

        rgb_frame      = np.ascontiguousarray(frame)
        h, w, ch       = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image   = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap     = QPixmap.fromImage(qt_image).scaled(
            PREVIEW_WIDTH, PREVIEW_HEIGHT,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.setPixmap(pixmap)

    # ── Ctrl + scroll zoom ─────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            zoom_step = 1.15 if delta > 0 else (1 / 1.15)
            self._zoom_factor = max(1.0, min(self._zoom_factor * zoom_step, 10.0))

            # Update zoom origin to cursor position (as fraction of widget)
            cursor_pos = event.position()
            self._zoom_origin_x = cursor_pos.x() / self.width()
            self._zoom_origin_y = cursor_pos.y() / self.height()

            self._render()
        else:
            super().wheelEvent(event)


# =============================================================================
# Format tooltip builder — single table covering all formats
# =============================================================================

def _build_all_formats_tooltip(
    sensor_mode: SensorMode | None,
    selected_fps: float,
    channels: int,
    write_speed_mbs: float | None,
    free_space_gb: float | None,
) -> str:
    """
    Build a monospace table covering all output formats at the
    currently selected resolution and framerate.
    Columns: Format | Description | Write rate | Size/min | Headroom | Max time
    """
    # ── Column widths ──────────────────────────────────────────────────────────
    W_FMT  = 22   # format name
    W_DESC = 38   # short description
    W_RATE = 12   # write rate
    W_SIZE = 11   # size per min
    W_HEAD = 10   # headroom
    W_TIME = 10   # max time

    header = (
        f"{'Format':<{W_FMT}}"
        f"{'Description':<{W_DESC}}"
        f"{'Write rate':>{W_RATE}}"
        f"{'Size/min':>{W_SIZE}}"
        f"{'Headroom':>{W_HEAD}}"
        f"{'Max time':>{W_TIME}}"
    )
    separator = "─" * (W_FMT + W_DESC + W_RATE + W_SIZE + W_HEAD + W_TIME)

    if sensor_mode is not None:
        colour_name = "greyscale" if channels == 1 else "colour"
        heading = (
            f"Output format comparison  —  {sensor_mode.width}×{sensor_mode.height} "
            f"@ {selected_fps:.1f} fps, {colour_name}"
        )
    else:
        heading = "Output format comparison"

    lines = [
        heading,
        separator,
        header,
        separator,
    ]

    # Short descriptions — one per format, matched by display_label
    DESCRIPTIONS = {
        "MJPEG video (.avi)": "Each frame compressed independently",
        "TIFF image stack":   "Uncompressed",
        "PNG image stack":    "Lossless compressed images",
        "H.264 video (.mp4)": "Inter-frame compr.: fast moves blur?",
    }

    icon = {"green": "✔", "amber": "⚠", "red": "✖"}

    if sensor_mode is None or write_speed_mbs is None:
        for display_label, _ext, _ in OUTPUT_FORMATS:
            desc = DESCRIPTIONS.get(display_label, "")
            lines.append(
                f"{display_label:<{W_FMT}}"
                f"{desc:<{W_DESC}}"
                f"{'—':>{W_RATE}}"
                f"{'—':>{W_SIZE}}"
                f"{'—':>{W_HEAD}}"
                f"{'—':>{W_TIME}}"
            )
    else:
        for display_label, _ext, _ in OUTPUT_FORMATS:
            desc         = DESCRIPTIONS.get(display_label, "")
            headroom     = compute_headroom(
                display_label, sensor_mode.width, sensor_mode.height,
                selected_fps, write_speed_mbs, channels,
            )
            size_per_min = estimate_file_size_per_minute_gb(
                display_label, sensor_mode.width, sensor_mode.height,
                selected_fps, channels,
            )
            max_time_str = "—"
            if free_space_gb is not None:
                max_time_s = compute_max_record_time_s(
                    display_label, sensor_mode.width, sensor_mode.height,
                    selected_fps, free_space_gb, channels,
                )
                if max_time_s is not None:
                    max_time_str = f"{max_time_s / 60:.0f} min"

            headroom_str = f"{headroom['headroom_pct']:.0f}% {icon[headroom['colour']]}"
            rate_str     = f"{headroom['write_rate_mbs']:.1f} MB/s"
            size_str     = f"{size_per_min:.2f} GB"

            lines.append(
                f"{display_label:<{W_FMT}}"
                f"{desc:<{W_DESC}}"
                f"{rate_str:>{W_RATE}}"
                f"{size_str:>{W_SIZE}}"
                f"{headroom_str:>{W_HEAD}}"
                f"{max_time_str:>{W_TIME}}"
            )

    lines.append(separator)
    if free_space_gb is not None and write_speed_mbs is not None:
        lines.append(
            f"Free: {free_space_gb:.1f} GB    "
            f"Write speed: {write_speed_mbs:.1f} MB/s    "
            f"Recalibrate: Settings → Recalibrate write speed"
        )
    else:
        lines.append("Calibrate write speed: Settings → Recalibrate write speed")

    return "\n".join(lines)


# =============================================================================
# Main window
# =============================================================================

class MainWindow(QMainWindow):

    frame_ready = pyqtSignal(np.ndarray)   # camera thread → UI thread

    def __init__(self):
        super().__init__()

        self._app_config     = load_app_config()
        self._profile        = default_profile()
        self._camera         = make_camera()
        self._is_recording   = False
        self._free_space_gb: float | None = None

        self.setWindowTitle(f"{APP_NAME}  {APP_VERSION}")
        self.setMinimumSize(1280, 780)
        self.setStyleSheet(STYLE_SHEET)

        self._build_menu()
        self._build_ui()
        self._populate_sensor_modes()
        self._on_format_changed(self._format_combo.currentIndex())
        self._refresh_free_space()
        self._start_preview()

        # Connect camera frames to preview widget via Qt signal (thread-safe)
        self.frame_ready.connect(self._preview_widget.update_frame)

    # =========================================================================
    # Menu bar
    # =========================================================================

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("File")
        load_action = QAction("Load profile…", self)
        load_action.triggered.connect(self._on_load_profile)
        save_action = QAction("Save profile…", self)
        save_action.triggered.connect(self._on_save_profile)
        file_menu.addAction(load_action)
        file_menu.addAction(save_action)

        # Settings menu
        settings_menu = menu_bar.addMenu("Settings")
        benchmark_action = QAction("Recalibrate write speed…", self)
        benchmark_action.triggered.connect(self._on_recalibrate_write_speed)
        settings_menu.addAction(benchmark_action)

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        outer_layout   = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)

        # ── Main splitter: preview (left) | controls (right) ──────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # Left: preview
        self._preview_widget = PreviewWidget()
        preview_panel        = self._build_preview_panel()
        splitter.addWidget(preview_panel)

        # Right: scrollable controls — fixed width so it never crowds the preview
        self._setup_panel    = self._build_setup_panel()
        self._status_panel   = self._build_status_panel()
        self._status_panel.setVisible(False)

        right_widget = QWidget()
        right_widget.setFixedWidth(420)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._setup_panel)
        right_layout.addWidget(self._status_panel)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)   # preview takes all remaining space
        splitter.setStretchFactor(1, 0)
        outer_layout.addWidget(splitter, stretch=1)

        # ── Bottom bar: record button + status ────────────────────────────────
        outer_layout.addWidget(self._build_bottom_bar())

        # Status bar
        self._status_bar_label = QLabel("Ready")
        self.statusBar().addWidget(self._status_bar_label)

    # ── Preview panel ──────────────────────────────────────────────────────────

    def _build_preview_panel(self) -> QWidget:
        panel  = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 4, 0)

        header = QLabel("Live preview")
        header.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 11px; text-transform: uppercase;")
        layout.addWidget(header)
        layout.addWidget(self._preview_widget)

        # Zoom hint
        zoom_hint = QLabel("Ctrl + scroll to zoom")
        zoom_hint.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 11px;")
        zoom_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(zoom_hint)
        layout.addStretch()
        return panel

    # ── Setup panel (right side, pre-recording) ────────────────────────────────

    def _build_setup_panel(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        container  = QWidget()
        layout     = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(6, 4, 12, 4)   # extra right margin avoids scrollbar overlap

        layout.addWidget(self._build_camera_group())
        layout.addWidget(self._build_output_group())
        layout.addWidget(self._build_metadata_group())
        layout.addWidget(self._build_profile_group())
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    # ── Camera settings group ──────────────────────────────────────────────────

    def _build_camera_group(self) -> QGroupBox:
        group  = QGroupBox("Camera")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        layout.setVerticalSpacing(6)

        row = 0

        # Sensor mode dropdown — sets resolution, bit depth, and the fps ceiling
        layout.addWidget(self._dim_label("Sensor mode"), row, 0)
        self._sensor_mode_combo = QComboBox()
        self._sensor_mode_combo.setFixedWidth(200)
        self._sensor_mode_combo.currentIndexChanged.connect(self._on_sensor_mode_changed)
        layout.addWidget(self._sensor_mode_combo, row, 1)
        row += 1

        # Framerate — any value up to the selected mode's maximum
        layout.addWidget(self._dim_label("Framerate"), row, 0)
        fps_row = QHBoxLayout()
        fps_row.setSpacing(6)
        self._fps_spin = QDoubleSpinBox()
        self._fps_spin.setRange(0.1, 250.0)
        self._fps_spin.setDecimals(1)
        self._fps_spin.setSuffix(" fps")
        self._fps_spin.setFixedWidth(100)
        self._fps_spin.valueChanged.connect(self._on_fps_changed)
        self._fps_max_label = QLabel("")
        self._fps_max_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        self._fps_info_btn = InfoButton(
            "The sensor mode sets the MAXIMUM framerate for that\n"
            "resolution and bit depth. Any lower framerate can be used.\n\n"
            "Low framerates are useful for:\n"
            "  · Timelapse-style image stacks (e.g. 1 fps or below)\n"
            "  · Long recordings where storage is the constraint\n"
            "  · Staying within the SD card's write budget at high resolution\n\n"
            "Lowering fps reduces the write rate proportionally, so it is the\n"
            "simplest way to gain write headroom without losing resolution."
        )
        fps_row.addWidget(self._fps_spin)
        fps_row.addWidget(self._fps_max_label)
        fps_row.addWidget(self._fps_info_btn)
        fps_row.addStretch()
        layout.addLayout(fps_row, row, 1)
        row += 1

        # Colour mode — greyscale uses only the Y plane (1 byte/px instead of 3)
        layout.addWidget(self._dim_label("Colour"), row, 0)
        colour_row = QHBoxLayout()
        colour_row.setSpacing(6)
        self._colour_combo = QComboBox()
        self._colour_combo.setFixedWidth(120)
        for colour_label, _channels in COLOUR_MODES:
            self._colour_combo.addItem(colour_label)
        default_index = self._colour_combo.findText(DEFAULT_COLOUR_MODE)
        if default_index >= 0:
            self._colour_combo.setCurrentIndex(default_index)
        self._colour_combo.currentIndexChanged.connect(self._on_colour_mode_changed)
        self._colour_info_btn = InfoButton(
            "Greyscale records only the luma (brightness) plane:\n"
            "1 byte per pixel instead of 3.\n\n"
            "  · ~3× smaller files for TIFF and PNG stacks\n"
            "  · ~2.5× smaller for MJPEG\n"
            "  · Correspondingly more write headroom\n\n"
            "Tracking algorithms work on brightness, not colour, so\n"
            "greyscale loses nothing relevant and is the recommended\n"
            "default. Choose Colour only if the analysis needs hue —\n"
            "for example distinguishing colour-marked individuals."
        )
        colour_row.addWidget(self._colour_combo)
        colour_row.addWidget(self._colour_info_btn)
        colour_row.addStretch()
        layout.addLayout(colour_row, row, 1)
        row += 1

        # Show preview toggle
        self._show_preview_check = QCheckBox("Show preview  (disable if Pi struggles)")
        self._show_preview_check.setChecked(True)
        self._show_preview_check.stateChanged.connect(self._on_preview_toggle)
        layout.addWidget(self._show_preview_check, row, 0, 1, 2)

        return group

    # ── Output settings group ──────────────────────────────────────────────────

    def _build_output_group(self) -> QGroupBox:
        group  = QGroupBox("Output")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        layout.setVerticalSpacing(6)

        row = 0

        # Save directory
        layout.addWidget(self._dim_label("Save to"), row, 0)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(4)
        self._save_dir_edit = QLineEdit(self._profile["recording"]["save_dir"])
        self._save_dir_edit.setMinimumWidth(120)
        browse_button       = QPushButton()
        browse_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        browse_button.setToolTip("Browse for save directory")
        browse_button.setFixedWidth(36)
        browse_button.clicked.connect(self._on_browse_save_dir)
        dir_row.addWidget(self._save_dir_edit)
        dir_row.addWidget(browse_button)
        layout.addLayout(dir_row, row, 1)
        row += 1

        # Format selector + ℹ popup for all-format comparison table
        layout.addWidget(self._dim_label("Format"), row, 0)
        format_row           = QHBoxLayout()
        format_row.setSpacing(4)
        self._format_combo   = QComboBox()
        self._format_combo.setMaxVisibleItems(len(OUTPUT_FORMATS))
        self._format_combo.setFixedWidth(160)
        for display_label, _, _ in OUTPUT_FORMATS:
            self._format_combo.addItem(display_label)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        self._format_info_btn = InfoButton()
        format_row.addWidget(self._format_combo)
        format_row.addWidget(self._format_info_btn)
        format_row.addStretch()
        layout.addLayout(format_row, row, 1)
        row += 1

        # Headroom indicator (updates live) + ℹ explaining what headroom means
        headroom_row = QHBoxLayout()
        headroom_row.setSpacing(4)
        self._headroom_label = QLabel("")
        self._headroom_label.setStyleSheet("font-size: 12px;")
        self._headroom_info_btn = InfoButton(
            "Write headroom is the fraction of your SD card's sustained write\n"
            "speed that is NOT used by the recording.\n\n"
            "Example: 30% headroom means the recording uses 70% of the card's\n"
            "write budget. At 0% the card can't keep up and frames are dropped.\n\n"
            "✔  > 30% — safe\n"
            "⚠  10–30% — marginal, frame drops possible under load\n"
            "✖  < 10% — expect frame drops\n\n"
            "Recalibrate under Settings if results seem off."
        )
        headroom_row.addWidget(self._headroom_label)
        headroom_row.addWidget(self._headroom_info_btn)
        headroom_row.addStretch()
        layout.addLayout(headroom_row, row, 0, 1, 2)
        row += 1

        # File / base name
        layout.addWidget(self._dim_label("File name"), row, 0)
        self._file_name_edit = QLineEdit(self._profile["recording"]["base_name"])
        self._file_name_edit.setMinimumWidth(120)
        layout.addWidget(self._file_name_edit, row, 1)
        row += 1

        # Folder name (image stack mode only)
        self._folder_name_label = self._dim_label("Folder name")
        layout.addWidget(self._folder_name_label, row, 0)
        self._folder_name_edit = QLineEdit(self._profile["recording"]["folder_name"])
        self._folder_name_edit.setMinimumWidth(120)
        layout.addWidget(self._folder_name_edit, row, 1)
        row += 1

        # Duration — checkbox on its own row, spinbox below
        layout.addWidget(self._dim_label("Duration"), row, 0)
        self._duration_check = QCheckBox("Record until stopped")
        self._duration_check.setChecked(True)
        self._duration_check.stateChanged.connect(self._on_duration_toggle)
        layout.addWidget(self._duration_check, row, 1)
        row += 1

        duration_row = QHBoxLayout()
        duration_row.setSpacing(6)
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 86400)
        self._duration_spin.setValue(60)
        self._duration_spin.setEnabled(False)
        self._duration_spin.setFixedWidth(100)
        duration_unit_label = QLabel("seconds")
        duration_unit_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        duration_row.addWidget(self._duration_spin)
        duration_row.addWidget(duration_unit_label)
        duration_row.addStretch()
        layout.addLayout(duration_row, row, 1)
        row += 1

        return group

    # ── Metadata group ─────────────────────────────────────────────────────────

    def _build_metadata_group(self) -> QGroupBox:
        group  = QGroupBox("Metadata")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        layout.setVerticalSpacing(6)

        meta = self._profile["metadata"]

        fields = [
            ("Experimenter", "experimenter"),
            ("Experiment",   "experiment"),
            ("Treatment",    "treatment"),
            ("Trial",        "trial"),
        ]
        self._meta_edits = {}
        for row, (label_text, key) in enumerate(fields):
            layout.addWidget(self._dim_label(label_text), row, 0)
            edit = QLineEdit(str(meta.get(key, "NA")))
            edit.setPlaceholderText("NA")
            edit.setMinimumWidth(120)
            self._meta_edits[key] = edit
            layout.addWidget(edit, row, 1)

        # ── Scale: px/cm OR frame width, on two compact rows ──────────────────
        row = len(fields)

        # Row 1: px/cm
        layout.addWidget(self._dim_label("Scale"), row, 0)
        px_row = QHBoxLayout()
        px_row.setSpacing(6)
        self._px_per_cm_spin = QDoubleSpinBox()
        self._px_per_cm_spin.setRange(0.1, 9999.0)
        self._px_per_cm_spin.setDecimals(2)
        self._px_per_cm_spin.setSpecialValueText("—")
        self._px_per_cm_spin.setValue(0.1)
        self._px_per_cm_spin.setFixedWidth(100)
        px_unit_label = QLabel("px/cm")
        px_unit_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        px_row.addWidget(self._px_per_cm_spin)
        px_row.addWidget(px_unit_label)
        px_row.addStretch()
        layout.addLayout(px_row, row, 1)
        row += 1

        # Row 2: or frame width
        or_label = QLabel("or")
        or_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        or_label.setMinimumWidth(100)
        or_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(or_label, row, 0)

        width_row = QHBoxLayout()
        width_row.setSpacing(6)
        self._frame_width_spin = QDoubleSpinBox()
        self._frame_width_spin.setRange(0.1, 999.0)
        self._frame_width_spin.setDecimals(1)
        self._frame_width_spin.setSpecialValueText("—")
        self._frame_width_spin.setValue(0.1)
        self._frame_width_spin.setFixedWidth(100)
        width_unit_label = QLabel("cm frame width")
        width_unit_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        width_row.addWidget(self._frame_width_spin)
        width_row.addWidget(width_unit_label)
        width_row.addStretch()
        layout.addLayout(width_row, row, 1)

        return group

    # ── Profile group ──────────────────────────────────────────────────────────

    def _build_profile_group(self) -> QGroupBox:
        group  = QGroupBox("Profile")
        layout = QHBoxLayout(group)

        load_button = QPushButton("Load profile…")
        save_button = QPushButton("Save profile…")
        load_button.clicked.connect(self._on_load_profile)
        save_button.clicked.connect(self._on_save_profile)
        layout.addWidget(load_button)
        layout.addWidget(save_button)
        layout.addStretch()
        return group

    # ── Status panel (right side, during recording) ────────────────────────────

    def _build_status_panel(self) -> QWidget:
        panel  = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        rec_label = QLabel("● RECORDING")
        rec_label.setStyleSheet(f"color: {COLOUR['red']}; font-size: 18px; font-weight: bold;")
        rec_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(rec_label)

        # Live stats — monospaced for alignment
        mono_font = QFont("DejaVu Sans Mono", 13)
        stats = [
            ("Elapsed",        "_elapsed_label"),
            ("Frames written", "_frames_label"),
            ("Dropped frames", "_dropped_label"),
            ("Write headroom", "_headroom_live_label"),
        ]
        grid = QGridLayout()
        for row, (stat_label, attr_name) in enumerate(stats):
            dim = self._dim_label(stat_label)
            val = QLabel("—")
            val.setFont(mono_font)
            val.setStyleSheet(f"color: {COLOUR['accent']};")
            setattr(self, attr_name, val)
            grid.addWidget(dim, row, 0)
            grid.addWidget(val, row, 1)

        layout.addLayout(grid)

        # Warnings area
        self._warning_label = QLabel("")
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(f"color: {COLOUR['red']}; font-size: 12px;")
        layout.addWidget(self._warning_label)

        layout.addStretch()
        return panel

    # ── Bottom bar ─────────────────────────────────────────────────────────────

    def _build_bottom_bar(self) -> QWidget:
        bar    = QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet(f"background-color: {COLOUR['panel']}; border-top: 1px solid {COLOUR['border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)

        self._record_button = QPushButton("▶  Start recording")
        self._record_button.setFixedHeight(38)
        self._record_button.setMinimumWidth(200)
        self._record_button.setStyleSheet(
            f"background-color: {COLOUR['button_start']}; color: white; "
            f"font-size: 14px; font-weight: bold; border-radius: 4px; border: none;"
        )
        self._record_button.clicked.connect(self._on_record_toggle)

        self._bottom_status = QLabel("Ready")
        self._bottom_status.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")

        layout.addWidget(self._record_button)
        layout.addSpacing(16)
        layout.addWidget(self._bottom_status)
        layout.addStretch()
        return bar

    # =========================================================================
    # Camera and preview
    # =========================================================================

    def _populate_sensor_modes(self) -> None:
        self._sensor_mode_combo.blockSignals(True)
        for mode in self._camera.sensor_modes:
            self._sensor_mode_combo.addItem(mode.display_label)
        self._sensor_mode_combo.blockSignals(False)
        self._on_sensor_mode_changed(0)

    def _start_preview(self) -> None:
        if self._show_preview_check.isChecked():
            self._camera.start_preview(
                callback = lambda frame: self.frame_ready.emit(frame),
                fps      = 10,
            )

    def _current_sensor_mode(self) -> SensorMode:
        index = self._sensor_mode_combo.currentIndex()
        return self._camera.sensor_modes[index]

    # =========================================================================
    # Headroom and tooltip refresh
    # =========================================================================

    def _refresh_free_space(self) -> None:
        save_dir = Path(self._save_dir_edit.text())
        if save_dir.exists():
            self._free_space_gb = get_free_space_gb(save_dir)

    def _refresh_headroom(self) -> None:
        """
        Update the inline headroom indicator for the selected format and
        push the all-formats comparison table to the format ℹ button.
        Uses the user-selected framerate, not the sensor mode maximum.
        """
        write_speed   = self._app_config["hardware"].get("sd_write_speed_mbs")
        mode          = self._current_sensor_mode()
        selected_fps  = self._fps_spin.value()
        channels      = self._current_channels()
        format_idx    = self._format_combo.currentIndex()
        format_label, _, _ = OUTPUT_FORMATS[format_idx]

        # Update the ℹ popup with the full comparison table
        table_text = _build_all_formats_tooltip(
            mode, selected_fps, channels, write_speed, self._free_space_gb,
        )
        self._format_info_btn.set_text(table_text)

        # Inline headroom for the currently selected format only
        if write_speed:
            headroom = compute_headroom(
                format_label, mode.width, mode.height, selected_fps,
                write_speed, channels,
            )
            colour = {
                "green": COLOUR["green"],
                "amber": COLOUR["amber"],
                "red":   COLOUR["red"],
            }[headroom["colour"]]
            icon = {"green": "✔", "amber": "⚠", "red": "✖"}[headroom["colour"]]
            self._headroom_label.setText(
                f"Write headroom: {headroom['headroom_pct']:.0f}%  {icon}"
            )
            self._headroom_label.setStyleSheet(f"color: {colour}; font-size: 12px;")
        else:
            self._headroom_label.setText("Write speed not calibrated")
            self._headroom_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")

    # =========================================================================
    # Slots
    # =========================================================================

    def _on_sensor_mode_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._camera.sensor_modes):
            return
        mode = self._camera.sensor_modes[index]
        self._camera.set_mode(mode)

        # Clamp the fps field to the new mode's ceiling, keeping the user's
        # value if it still fits.
        self._fps_spin.blockSignals(True)
        self._fps_spin.setMaximum(mode.max_fps)
        if self._fps_spin.value() > mode.max_fps:
            self._fps_spin.setValue(mode.max_fps)
        elif self._fps_spin.value() <= 0.1:
            self._fps_spin.setValue(mode.max_fps)
        self._fps_spin.blockSignals(False)

        self._fps_max_label.setText(f"max {mode.max_fps:.1f}")
        self._refresh_headroom()

    def _on_fps_changed(self, _value: float) -> None:
        self._refresh_headroom()

    def _on_colour_mode_changed(self, _index: int) -> None:
        self._refresh_headroom()

    def _current_channels(self) -> int:
        """Return 1 for greyscale, 3 for colour."""
        label = self._colour_combo.currentText()
        for colour_label, channels in COLOUR_MODES:
            if colour_label == label:
                return channels
        return 3

    def _on_format_changed(self, _index: int) -> None:
        self._refresh_headroom()
        # Folder name applies to image stacks only; file name to both
        format_label   = self._format_combo.currentText()
        is_image_stack = "stack" in format_label.lower()
        self._folder_name_edit.setEnabled(is_image_stack)
        self._folder_name_label.setEnabled(is_image_stack)
        if is_image_stack:
            self._folder_name_edit.setToolTip(
                "Images are written into this folder, named "
                "{file name}_00001.tiff, _00002.tiff, and so on."
            )
        else:
            self._folder_name_edit.setToolTip(
                "Only used for image stacks — video formats write a single file."
            )

    def _on_preview_toggle(self, state: int) -> None:
        if state == Qt.CheckState.Checked.value:
            self._start_preview()
            self._preview_widget.setText("")
        else:
            self._camera.stop_preview()
            self._preview_widget.setText("Preview disabled")

    def _on_browse_save_dir(self) -> None:
        chosen_dir = QFileDialog.getExistingDirectory(
            self, "Select save directory", self._save_dir_edit.text()
        )
        if chosen_dir:
            self._save_dir_edit.setText(chosen_dir)
            self._refresh_free_space()
            self._refresh_headroom()

    def _on_duration_toggle(self, state: int) -> None:
        self._duration_spin.setEnabled(state != Qt.CheckState.Checked.value)

    def _on_record_toggle(self) -> None:
        if self._is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        # Placeholder — wired up when record logic is added
        self._is_recording = True
        self._setup_panel.setVisible(False)
        self._status_panel.setVisible(True)
        self._record_button.setText("■  Stop recording")
        self._record_button.setStyleSheet(
            f"background-color: {COLOUR['button_stop']}; color: white; "
            f"font-size: 14px; font-weight: bold; border-radius: 4px; border: none;"
        )
        self._bottom_status.setText("Recording…")

    def _stop_recording(self) -> None:
        # Placeholder — wired up when record logic is added
        self._is_recording = False
        self._setup_panel.setVisible(True)
        self._status_panel.setVisible(False)
        self._record_button.setText("▶  Start recording")
        self._record_button.setStyleSheet(
            f"background-color: {COLOUR['button_start']}; color: white; "
            f"font-size: 14px; font-weight: bold; border-radius: 4px; border: none;"
        )
        self._bottom_status.setText("Ready")

    def _on_load_profile(self) -> None:
        profile_file, _ = QFileDialog.getOpenFileName(
            self, "Load profile", self._save_dir_edit.text(), "YAML files (*.yaml *.yml)"
        )
        if profile_file:
            self._profile = load_profile(Path(profile_file))
            self._apply_profile_to_ui()

    def _on_save_profile(self) -> None:
        profile_file, _ = QFileDialog.getSaveFileName(
            self, "Save profile", self._save_dir_edit.text(), "YAML files (*.yaml *.yml)"
        )
        if profile_file:
            save_profile(self._collect_profile_from_ui(), Path(profile_file))

    def _on_recalibrate_write_speed(self) -> None:
        from benchmark import measure_write_speed_mbs
        from PyQt6.QtWidgets import QMessageBox
        save_dir = Path(self._save_dir_edit.text())
        if not save_dir.exists():
            QMessageBox.warning(self, "Error", f"Save directory does not exist:\n{save_dir}")
            return
        self._bottom_status.setText("Measuring write speed… (this takes ~10 s)")
        QApplication.processEvents()
        write_speed_mbs = measure_write_speed_mbs(save_dir)
        self._app_config["hardware"]["sd_write_speed_mbs"] = write_speed_mbs
        from datetime import date
        self._app_config["hardware"]["sd_write_speed_measured_date"] = str(date.today())
        save_app_config(self._app_config)
        self._refresh_headroom()
        self._bottom_status.setText(f"Write speed: {write_speed_mbs:.1f} MB/s  (calibrated today)")

    # =========================================================================
    # Profile helpers
    # =========================================================================

    def _collect_profile_from_ui(self) -> dict:
        return {
            "recording": {
                "save_dir":      self._save_dir_edit.text(),
                "output_format": self._format_combo.currentText(),
                "duration_s":    None if self._duration_check.isChecked() else self._duration_spin.value(),
                "base_name":     self._file_name_edit.text(),
                "folder_name":   self._folder_name_edit.text(),
            },
            "camera": {
                "sensor_mode": self._sensor_mode_combo.currentIndex(),
                "fps":         self._fps_spin.value(),
                "colour_mode": self._colour_combo.currentText(),
            },
            "metadata": {
                key: edit.text() for key, edit in self._meta_edits.items()
            } | {
                "px_per_cm":   self._px_per_cm_spin.value(),
                "frame_width_cm": self._frame_width_spin.value(),
            },
        }

    def _apply_profile_to_ui(self) -> None:
        rec  = self._profile.get("recording", {})
        meta = self._profile.get("metadata",  {})
        cam  = self._profile.get("camera",    {})

        if "save_dir"      in rec: self._save_dir_edit.setText(rec["save_dir"])
        if "output_format" in rec:
            index = self._format_combo.findText(rec["output_format"])
            if index >= 0:
                self._format_combo.setCurrentIndex(index)
        if "base_name"     in rec: self._file_name_edit.setText(rec["base_name"])
        if "folder_name"   in rec: self._folder_name_edit.setText(rec["folder_name"])
        if "duration_s"    in rec:
            if rec["duration_s"] is None:
                self._duration_check.setChecked(True)
            else:
                self._duration_check.setChecked(False)
                self._duration_spin.setValue(int(rec["duration_s"]))

        for key, edit in self._meta_edits.items():
            if key in meta:
                edit.setText(str(meta[key]))

        if "sensor_mode" in cam and cam["sensor_mode"] is not None:
            self._sensor_mode_combo.setCurrentIndex(cam["sensor_mode"])
        # fps must be applied after sensor_mode, since the mode sets the ceiling
        if "fps" in cam and cam["fps"] is not None:
            self._fps_spin.setValue(float(cam["fps"]))
        if "colour_mode" in cam and cam["colour_mode"]:
            colour_index = self._colour_combo.findText(cam["colour_mode"])
            if colour_index >= 0:
                self._colour_combo.setCurrentIndex(colour_index)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _dim_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        label.setMinimumWidth(100)
        label.setMaximumWidth(100)
        return label

    # =========================================================================
    # Cleanup
    # =========================================================================

    def closeEvent(self, event) -> None:
        self._camera.release()
        super().closeEvent(event)
