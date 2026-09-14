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

import os      # only for os.access — pathlib has no equivalent
import time
from pathlib import Path

from PyQt6.QtCore    import Qt, QTimer, pyqtSignal, QThread, QPoint, QSize
from PyQt6.QtGui     import QImage, QPixmap, QFont, QColor, QPalette, QAction, QCursor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QGridLayout, QSplitter,
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QToolTip, QStatusBar, QMenuBar,
    QGroupBox, QSizePolicy, QFrame, QScrollArea, QTextEdit, QStyle,
    QRadioButton, QButtonGroup, QListWidget, QListWidgetItem, QAbstractItemView,
)

import numpy as np

from constants  import (
    APP_NAME, APP_VERSION, DEFAULT_SAVE_DIR,
    FILENAME_FIELDS, DEFAULT_FIELD_ORDER,
    PREVIEW_WIDTH,
    OUTPUT_FORMATS, METADATA_DEFAULTS,
    COLOUR_MODES, DEFAULT_COLOUR_MODE,
)
from config     import load_app_config, save_app_config, load_profile, save_profile, default_profile
from benchmark  import (
    get_free_space_gb, compute_headroom, compute_max_record_time_s,
    estimate_file_size_per_minute_gb,
)
from camera     import make_camera, SensorMode
from record     import RecordingSession, RecordingSettings
from metadata   import build_metadata, write_metadata
from metadata_list import load_metadata_list, build_auto_file_name, MetadataRow


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
    QRadioButton {{
        color: {COLOUR["text"]};
        font-size: 12px;
        spacing: 5px;
    }}
    QRadioButton::indicator {{
        width: 12px;
        height: 12px;
        border-radius: 7px;
        border: 1px solid {COLOUR["border"]};
        background-color: {COLOUR["bg"]};
    }}
    QRadioButton::indicator:checked {{
        background-color: {COLOUR["accent"]};
        border: 3px solid {COLOUR["bg"]};
        outline: 1px solid {COLOUR["accent"]};
    }}
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
# Metadata field list — reorderable rows that build the file name
# =============================================================================
#
# The order of rows here IS the order of components in the automatic file name.
# Rows are dragged by their handle; dragging from anywhere else would fight
# with selecting text inside the fields, so the list only permits a drag that
# began on a handle (see MetadataFieldList.mousePressEvent).

DRAG_HANDLE_GLYPH = "\u2261"


class _DragHandle(QLabel):
    """The grip at the left of a row. Visual only — the list does the dragging."""

    SIZE = 22

    def __init__(self, parent=None):
        super().__init__(DRAG_HANDLE_GLYPH, parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder — the order sets the file name")
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {COLOUR['bg']};
                color: {COLOUR['text_dim']};
                border: 1px solid {COLOUR['border']};
                border-radius: 3px;
                font-size: 13px;
            }}
        """)


class FixedFieldRow(QWidget):
    """A built-in metadata field: experiment, ant_id or trial."""

    changed = pyqtSignal()

    def __init__(self, field_key: str, label_text: str, value: str = "", parent=None):
        super().__init__(parent)
        self.field_key = field_key
        self.kind      = "field"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.handle = _DragHandle()

        label = QLabel(label_text)
        label.setFixedWidth(78)
        label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")

        self.value_edit = QLineEdit(value)
        self.value_edit.setPlaceholderText("NA")
        self.value_edit.setMinimumWidth(70)
        self.value_edit.textChanged.connect(self.changed)

        layout.addWidget(self.handle)
        layout.addWidget(label)
        layout.addWidget(self.value_edit)

    def get_component(self) -> tuple[str, str, str]:
        return ("field", self.field_key, self.value_edit.text().strip())

    def set_value(self, value: str) -> None:
        self.value_edit.setText(str(value))


class TreatmentRow(QWidget):
    """A user-defined treatment: editable name, editable value, remove button."""

    removed = pyqtSignal(object)
    changed = pyqtSignal()

    def __init__(self, name: str = "", value: str = "", parent=None):
        super().__init__(parent)
        self.kind = "treatment"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.handle = _DragHandle()

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("name")
        self.name_edit.setFixedWidth(78)
        self.name_edit.textChanged.connect(self.changed)

        self.value_edit = QLineEdit(value)
        self.value_edit.setPlaceholderText("value")
        self.value_edit.setMinimumWidth(60)
        self.value_edit.textChanged.connect(self.changed)

        remove_button = QPushButton("\u2715")
        remove_button.setFixedSize(22, 22)
        remove_button.setToolTip("Remove this treatment")
        remove_button.setStyleSheet(
            f"color: {COLOUR['text_dim']}; font-size: 11px; padding: 0;"
        )
        remove_button.clicked.connect(lambda: self.removed.emit(self))

        layout.addWidget(self.handle)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.value_edit)
        layout.addWidget(remove_button)

    def get_component(self) -> tuple[str, str, str]:
        return ("treatment",
                self.name_edit.text().strip(),
                self.value_edit.text().strip())


class MetadataFieldList(QListWidget):
    """
    Ordered, drag-reorderable list of metadata rows.

    Qt's InternalMove drag mode normally starts a drag from anywhere on an
    item, which would make it impossible to select text inside the row's line
    edits. Dragging is therefore enabled only for presses that land on a row's
    handle, and disabled again immediately afterwards.
    """

    changed = pyqtSignal()
    ROW_HEIGHT = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(False)          # enabled per-press, see below
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item { background: transparent; border: none; padding: 0px; }
            QListWidget::item:selected { background: transparent; }
        """)
        self.model().rowsMoved.connect(lambda *_: self.changed.emit())

    # -- Row management --------------------------------------------------------

    def _add_widget_row(self, widget: QWidget) -> None:
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, self.ROW_HEIGHT))
        self.addItem(item)
        self.setItemWidget(item, widget)
        widget.changed.connect(self.changed)
        if isinstance(widget, TreatmentRow):
            widget.removed.connect(self._remove_treatment)
        self._resize_to_contents()

    def add_field(self, field_key: str, label_text: str, value: str = ""):
        row = FixedFieldRow(field_key, label_text, value)
        self._add_widget_row(row)
        return row

    def add_treatment(self, name: str = "", value: str = ""):
        row = TreatmentRow(name, value)
        self._add_widget_row(row)
        self.changed.emit()
        return row

    def _remove_treatment(self, row) -> None:
        for index in range(self.count()):
            if self.itemWidget(self.item(index)) is row:
                self.takeItem(index)
                row.deleteLater()
                self._resize_to_contents()
                self.changed.emit()
                return

    def _resize_to_contents(self) -> None:
        # The list sits inside a scroll area, so it must be exactly tall enough
        # for its rows — otherwise it either clips or leaves a gap.
        self.setFixedHeight(max(1, self.count()) * self.ROW_HEIGHT + 4)

    # -- Access ----------------------------------------------------------------

    def rows(self) -> list:
        return [self.itemWidget(self.item(i)) for i in range(self.count())]

    def get_components(self) -> list:
        """Ordered (kind, name, value) tuples — the file name is built from these."""
        return [row.get_component() for row in self.rows() if row is not None]

    def get_field_values(self) -> dict:
        return {row.field_key: row.value_edit.text().strip()
                for row in self.rows() if isinstance(row, FixedFieldRow)}

    def get_treatments(self) -> dict:
        treatments = {}
        for row in self.rows():
            if isinstance(row, TreatmentRow):
                _, name, value = row.get_component()
                if name and value:
                    treatments[name] = value
        return treatments

    def get_order(self) -> list:
        """Row order as keys, for saving in a profile: field keys and 'treatment'."""
        return [row.field_key if isinstance(row, FixedFieldRow) else "treatment"
                for row in self.rows()]

    def set_field_value(self, field_key: str, value: str) -> None:
        for row in self.rows():
            if isinstance(row, FixedFieldRow) and row.field_key == field_key:
                row.set_value(value)
                return

    def clear_treatments(self) -> None:
        for index in reversed(range(self.count())):
            if isinstance(self.itemWidget(self.item(index)), TreatmentRow):
                self.takeItem(index)
        self._resize_to_contents()

    def set_treatments(self, treatments: dict) -> None:
        """Replace all treatments with the given name/value pairs."""
        self.clear_treatments()
        for name, value in (treatments or {}).items():
            self.add_treatment(str(name), str(value))

    # -- Drag gating -----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        """Permit a drag only when the press landed on a row's handle."""
        item = self.itemAt(event.pos())
        on_handle = False
        if item is not None:
            widget = self.itemWidget(item)
            if widget is not None and hasattr(widget, "handle"):
                handle_top_left = widget.mapTo(self, widget.handle.pos())
                handle_rect = widget.handle.rect()
                handle_rect.moveTopLeft(handle_top_left)
                on_handle = handle_rect.contains(event.pos())
        self.setDragEnabled(on_handle)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.setDragEnabled(False)



# =============================================================================
# Preview widget — displays camera frames, handles ctrl+scroll zoom
# =============================================================================

class PreviewWidget(QLabel):
    """
    Displays numpy frames from the camera preview stream.

    Mouse controls:
      Ctrl + scroll   zoom in/out, centred on the cursor
      scroll          pan up/down   (when zoomed in)
      Shift + scroll  pan left/right (when zoomed in)

    The view is described by a zoom factor and a centre point in normalised
    frame coordinates. The centre is clamped so the visible crop can never
    extend past the frame edge — clamping the centre rather than the crop
    is what prevents the view from jumping when you pan into a corner.
    """

    zoom_changed = pyqtSignal(float)

    _MIN_ZOOM  = 1.0
    _MAX_ZOOM  = 12.0
    _ZOOM_STEP = 1.15
    _PAN_STEP  = 0.06     # fraction of the visible width/height per scroll notch

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background-color: #0A0C0E; border: 1px solid {COLOUR['border']}; "
            f"border-radius: 4px;"
        )
        self.setText("No camera signal")

        self._zoom_factor   = 1.0
        self._centre_x      = 0.5    # normalised centre of the visible region
        self._centre_y      = 0.5
        self._current_frame: np.ndarray | None = None

    # ── Frame ingestion ────────────────────────────────────────────────────────

    def update_frame(self, frame_array: np.ndarray) -> None:
        self._current_frame = frame_array
        self._render()

    def _render(self) -> None:
        if self._current_frame is None:
            return

        frame = self._current_frame

        # Normalise to RGB — the camera may deliver greyscale (2D) or RGBA
        if frame.ndim == 2:
            frame = np.stack([frame, frame, frame], axis=2)
        elif frame.shape[2] == 4:
            frame = frame[:, :, :3]

        frame_height, frame_width = frame.shape[:2]

        if self._zoom_factor > 1.0:
            crop_width  = max(1, int(frame_width  / self._zoom_factor))
            crop_height = max(1, int(frame_height / self._zoom_factor))
            left = int(self._centre_x * frame_width  - crop_width  / 2)
            top  = int(self._centre_y * frame_height - crop_height / 2)
            # Centre is already clamped, so these are belt-and-braces only
            left = max(0, min(left, frame_width  - crop_width))
            top  = max(0, min(top,  frame_height - crop_height))
            frame = frame[top:top + crop_height, left:left + crop_width]

        rgb_frame      = np.ascontiguousarray(frame)
        height, width, channels = rgb_frame.shape
        bytes_per_line = channels * width
        qt_image = QImage(
            rgb_frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888
        )
        # Scale to the widget's CURRENT size, so the whole frame is always
        # visible regardless of window size or frame aspect ratio
        pixmap = QPixmap.fromImage(qt_image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        # Re-render at the new widget size so the frame refits immediately
        self._render()
        super().resizeEvent(event)

    # ── View manipulation ──────────────────────────────────────────────────────

    def _clamp_centre(self) -> None:
        """
        Keep the visible region inside the frame. At zoom Z the visible region
        is 1/Z of the frame, so the centre must stay at least half of that
        away from each edge.
        """
        half_extent = 0.5 / self._zoom_factor
        lower, upper = half_extent, 1.0 - half_extent
        if lower >= upper:          # fully zoomed out
            self._centre_x = self._centre_y = 0.5
        else:
            self._centre_x = max(lower, min(self._centre_x, upper))
            self._centre_y = max(lower, min(self._centre_y, upper))

    def reset_view(self) -> None:
        self._zoom_factor = 1.0
        self._centre_x = self._centre_y = 0.5
        self.zoom_changed.emit(self._zoom_factor)
        self._render()

    def wheelEvent(self, event) -> None:
        notches   = event.angleDelta().y() / 120.0
        modifiers = event.modifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._zoom_at_cursor(event, notches)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            self._pan(dx_notches=notches, dy_notches=0.0)
        else:
            self._pan(dx_notches=0.0, dy_notches=notches)

        event.accept()

    def _zoom_at_cursor(self, event, notches: float) -> None:
        """
        Zoom about the cursor: the frame point under the cursor stays under
        the cursor. Without this the view appears to slide as you zoom.
        """
        old_zoom = self._zoom_factor
        new_zoom = old_zoom * (self._ZOOM_STEP ** notches)
        new_zoom = max(self._MIN_ZOOM, min(new_zoom, self._MAX_ZOOM))
        if new_zoom == old_zoom:
            return

        # Cursor position as a fraction of the widget, offset from its centre
        cursor    = event.position()
        offset_x  = (cursor.x() / max(1, self.width()))  - 0.5
        offset_y  = (cursor.y() / max(1, self.height())) - 0.5

        # Frame coordinate currently under the cursor
        frame_x = self._centre_x + offset_x / old_zoom
        frame_y = self._centre_y + offset_y / old_zoom

        # Move the centre so that same coordinate stays under the cursor
        self._centre_x = frame_x - offset_x / new_zoom
        self._centre_y = frame_y - offset_y / new_zoom
        self._zoom_factor = new_zoom

        self._clamp_centre()
        self.zoom_changed.emit(self._zoom_factor)
        self._render()

    def _pan(self, dx_notches: float, dy_notches: float) -> None:
        """Pan the view. Step size scales with zoom so it feels consistent."""
        if self._zoom_factor <= 1.0:
            return   # nothing to pan when the whole frame is visible

        step = self._PAN_STEP / self._zoom_factor
        # Scrolling up (positive notches) moves the view up, i.e. centre down
        self._centre_x -= dx_notches * step
        self._centre_y -= dy_notches * step

        self._clamp_centre()
        self._render()

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-click resets the view to fully zoomed out."""
        self.reset_view()
        super().mouseDoubleClickEvent(event)


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

        # Metadata list (CSV) state
        self._metadata_rows: list = []
        self._metadata_list_file = None

        # Spatial calibration anchor: the scene width the FULL sensor would
        # see, in cm. Stored independently of sensor mode so the calibration
        # survives mode changes correctly. None = not calibrated.
        self._full_fov_width_cm: float | None = None

        # Recording state
        self._session: RecordingSession | None = None
        self._is_finishing = False
        self._recording_settings: RecordingSettings | None = None
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_recording_status)

        self.setWindowTitle(f"{APP_NAME}  {APP_VERSION}")
        # Wide enough for a 4:3 preview (the tallest aspect the sensor offers)
        # beside the fixed 420 px control panel, without manual resizing
        self.setMinimumSize(1180, 700)
        self.resize(1500, 900)
        self.setStyleSheet(STYLE_SHEET)

        self._build_menu()
        self._build_ui()
        self._populate_sensor_modes()          # also sets initial fps on the camera
        self._camera.set_colour_mode(self._current_channels())
        self._on_format_changed(self._format_combo.currentIndex())
        self._on_scale_mode_changed()          # sets which scale field is editable
        self._on_auto_name_toggled(0)          # applies auto file naming
        self._ensure_save_dir_usable()
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

        settings_menu.addSeparator()

        # File naming: whether treatment names appear alongside their values
        self._treatment_names_action = QAction("Include treatment names in file name", self)
        self._treatment_names_action.setCheckable(True)
        self._treatment_names_action.setChecked(
            self._app_config["app"].get("include_treatment_names", False)
        )
        self._treatment_names_action.toggled.connect(self._on_treatment_names_toggled)
        settings_menu.addAction(self._treatment_names_action)

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
        layout.setSpacing(4)

        # Header row: title on the left, zoom readout on the right
        header_row = QHBoxLayout()
        header = QLabel("Live preview")
        header.setStyleSheet(
            f"color: {COLOUR['text_dim']}; font-size: 11px; text-transform: uppercase;"
        )
        self._zoom_label = QLabel("zoom 1.0×")
        self._zoom_label.setStyleSheet(
            f"color: {COLOUR['text_dim']}; font-size: 11px; "
            f"font-family: 'DejaVu Sans Mono', monospace;"
        )
        self._zoom_reset_button = QPushButton("Reset view")
        self._zoom_reset_button.setFixedHeight(20)
        self._zoom_reset_button.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        self._zoom_reset_button.setVisible(False)
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(self._zoom_label)
        header_row.addWidget(self._zoom_reset_button)
        layout.addLayout(header_row)

        layout.addWidget(self._preview_widget, stretch=1)

        # Control hints
        zoom_hint = QLabel(
            "Ctrl + scroll: zoom     ·     scroll: pan up/down     ·     "
            "Shift + scroll: pan left/right     ·     double-click: reset"
        )
        zoom_hint.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 11px;")
        zoom_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(zoom_hint)

        # Wire zoom readout
        self._preview_widget.zoom_changed.connect(self._on_zoom_changed)
        self._zoom_reset_button.clicked.connect(self._preview_widget.reset_view)

        return panel

    def _on_zoom_changed(self, zoom_factor: float) -> None:
        self._zoom_label.setText(f"zoom {zoom_factor:.1f}×")
        is_zoomed = zoom_factor > 1.001
        self._zoom_reset_button.setVisible(is_zoomed)
        self._zoom_label.setStyleSheet(
            f"color: {COLOUR['accent'] if is_zoomed else COLOUR['text_dim']}; "
            f"font-size: 11px; font-family: 'DejaVu Sans Mono', monospace;"
        )

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
        self._fps_spin.setFixedWidth(80)
        self._fps_spin.valueChanged.connect(self._on_fps_changed)
        fps_unit_label = QLabel("fps")
        fps_unit_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
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
        fps_row.addWidget(fps_unit_label)
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

        # File name — auto-generated from metadata unless overridden
        auto_name_row = QHBoxLayout()
        auto_name_row.setSpacing(4)
        self._auto_name_check = QCheckBox("Name from metadata")
        self._auto_name_check.setChecked(True)
        self._auto_name_check.stateChanged.connect(self._on_auto_name_toggled)
        self._auto_name_info_btn = InfoButton(
            "When ticked, the file name is built automatically from the\n"
            "metadata fields:\n\n"
            "    {experiment}_{treatments}_{trial}\n\n"
            "Treatments are joined with '-'. Whether treatment NAMES are\n"
            "included alongside their values is set under\n"
            "Settings → File naming.\n\n"
            "    values only:  foraging_high-dim_3\n"
            "    with names:   foraging_density-high-light-dim_3\n\n"
            "Untick to type a name yourself. Parts that are empty or 'NA'\n"
            "are left out rather than appearing literally."
        )
        auto_name_row.addWidget(self._auto_name_check)
        auto_name_row.addWidget(self._auto_name_info_btn)
        auto_name_row.addStretch()
        layout.addLayout(auto_name_row, row, 1)
        row += 1

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
        row  = 0

        # ── Load metadata from a CSV list ──────────────────────────────────────
        load_row = QHBoxLayout()
        load_row.setSpacing(4)
        self._load_list_button = QPushButton("Load metadata from file…")
        self._load_list_button.setStyleSheet("font-size: 11px; padding: 3px 10px;")
        self._load_list_button.clicked.connect(self._on_load_metadata_list)
        self._list_info_btn = InfoButton(
            "Load a CSV of planned sessions and step through it between\n"
            "recordings, instead of typing metadata each time.\n\n"
            "COLUMN CONVENTION\n"
            "  Three column names are reserved:\n"
            "      experimenter, experiment, trial\n"
            "  EVERY OTHER COLUMN IS TREATED AS A TREATMENT — the column\n"
            "  name becomes the treatment name, the cell becomes its value.\n\n"
            "EXAMPLE\n"
            "      experiment,trial,density,light\n"
            "      foraging,1,high,dim\n"
            "      foraging,2,low,bright\n\n"
            "  gives two sessions, each with a density and a light treatment.\n\n"
            "Fields stay editable after loading, so you can adjust on the fly.\n"
            "The list advances automatically when a recording finishes.\n"
            "A ✓ marks rows whose output file already exists."
        )
        load_row.addWidget(self._load_list_button)
        load_row.addWidget(self._list_info_btn)
        load_row.addStretch()
        layout.addLayout(load_row, row, 0, 1, 2)
        row += 1

        # Navigation through the loaded list (hidden until a list is loaded)
        self._list_nav_widget = QWidget()
        nav_layout = QHBoxLayout(self._list_nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)

        self._list_prev_button = QPushButton("◀")
        self._list_prev_button.setFixedWidth(28)
        self._list_prev_button.setToolTip("Previous row  (Left arrow)")
        self._list_prev_button.clicked.connect(lambda: self._step_metadata_list(-1))

        self._list_combo = QComboBox()
        self._list_combo.setMinimumWidth(150)
        self._list_combo.currentIndexChanged.connect(self._on_list_row_selected)

        self._list_next_button = QPushButton("▶")
        self._list_next_button.setFixedWidth(28)
        self._list_next_button.setToolTip("Next row  (Right arrow)")
        self._list_next_button.clicked.connect(lambda: self._step_metadata_list(+1))

        self._list_clear_button = QPushButton("✕")
        self._list_clear_button.setFixedWidth(24)
        self._list_clear_button.setToolTip("Close the list and type metadata manually")
        self._list_clear_button.clicked.connect(self._on_clear_metadata_list)

        nav_layout.addWidget(self._list_prev_button)
        nav_layout.addWidget(self._list_combo, stretch=1)
        nav_layout.addWidget(self._list_next_button)
        nav_layout.addWidget(self._list_clear_button)
        self._list_nav_widget.setVisible(False)
        layout.addWidget(self._list_nav_widget, row, 0, 1, 2)
        row += 1

        # ── Experimenter — not part of the file name, so not in the list ──────
        layout.addWidget(self._dim_label("Experimenter"), row, 0)
        self._experimenter_edit = QLineEdit(str(meta.get("experimenter", "NA")))
        self._experimenter_edit.setPlaceholderText("NA")
        self._experimenter_edit.setMinimumWidth(120)
        layout.addWidget(self._experimenter_edit, row, 1)
        row += 1

        # ── Ordered fields: these build the file name, in this order ───────────
        name_header = QHBoxLayout()
        name_header.setSpacing(4)
        name_header_label = QLabel("File name fields")
        name_header_label.setStyleSheet(
            f"color: {COLOUR['text_dim']}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.06em;"
        )
        self._field_order_info_btn = InfoButton(
            "These fields build the automatic file name, IN THIS ORDER.\n\n"
            "Drag a row by its \u2261 handle to reorder it; the file name\n"
            "updates as you drag.\n\n"
            "  experiment, ant_id, trial, density, light\n"
            "      \u2192  foraging_A01_1_high-dim\n\n"
            "  ant_id, experiment, trial, density, light\n"
            "      \u2192  A01_foraging_1_high-dim\n\n"
            "Treatments that sit next to each other are joined with '-';\n"
            "everything else is separated by '_'. Fields left empty or 'NA'\n"
            "are skipped rather than appearing in the name.\n\n"
            "Experimenter is deliberately not here: it identifies the person\n"
            "rather than the recording, so it would lengthen every name\n"
            "without making them more distinguishable."
        )
        name_header.addWidget(name_header_label)
        name_header.addWidget(self._field_order_info_btn)
        name_header.addStretch()
        layout.addLayout(name_header, row, 0, 1, 2)
        row += 1

        self._field_list = MetadataFieldList()
        for field_key, label_text in FILENAME_FIELDS:
            self._field_list.add_field(
                field_key, label_text, str(meta.get(field_key, "NA"))
            )
        self._field_list.changed.connect(self._refresh_auto_file_name)
        layout.addWidget(self._field_list, row, 0, 1, 2)
        row += 1

        add_treatment_row = QHBoxLayout()
        add_treatment_button = QPushButton("+  Add treatment")
        add_treatment_button.setStyleSheet("font-size: 11px; padding: 3px 10px;")
        add_treatment_button.clicked.connect(lambda: self._field_list.add_treatment())
        add_treatment_row.addWidget(add_treatment_button)
        add_treatment_row.addStretch()
        layout.addLayout(add_treatment_row, row, 0, 1, 2)
        row += 1

        # ── Scale: choose which value you enter; the other is computed ────────
        layout.addWidget(self._dim_label("Scale"), row, 0)
        scale_mode_row = QHBoxLayout()
        scale_mode_row.setSpacing(10)
        self._scale_px_radio    = QRadioButton("px/cm")
        self._scale_width_radio = QRadioButton("frame width")
        # Frame width is the default because it is the one you can measure
        # directly with a ruler in the arena; px/cm is derived from it.
        self._scale_width_radio.setChecked(True)
        self._scale_button_group = QButtonGroup(self)
        self._scale_button_group.addButton(self._scale_px_radio,    0)
        self._scale_button_group.addButton(self._scale_width_radio, 1)
        self._scale_px_radio.toggled.connect(self._on_scale_mode_changed)
        self._scale_width_radio.toggled.connect(self._on_scale_mode_changed)
        scale_mode_row.addWidget(self._scale_px_radio)
        scale_mode_row.addWidget(self._scale_width_radio)
        scale_mode_row.addStretch()
        layout.addLayout(scale_mode_row, row, 1)
        row += 1

        # px/cm entry
        px_row = QHBoxLayout()
        px_row.setSpacing(6)
        self._px_per_cm_spin = QDoubleSpinBox()
        self._px_per_cm_spin.setRange(0.0, 99999.0)
        self._px_per_cm_spin.setDecimals(1)
        self._px_per_cm_spin.setSpecialValueText("—")
        self._px_per_cm_spin.setValue(0.0)
        self._px_per_cm_spin.setFixedWidth(100)
        self._px_per_cm_spin.valueChanged.connect(self._on_px_per_cm_changed)
        px_unit_label = QLabel("px/cm")
        px_unit_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        px_row.addWidget(self._px_per_cm_spin)
        px_row.addWidget(px_unit_label)
        px_row.addStretch()
        layout.addLayout(px_row, row, 1)
        row += 1

        # frame width entry
        width_row = QHBoxLayout()
        width_row.setSpacing(6)
        self._frame_width_spin = QDoubleSpinBox()
        self._frame_width_spin.setRange(0.0, 999.0)
        self._frame_width_spin.setDecimals(1)
        self._frame_width_spin.setSpecialValueText("—")
        self._frame_width_spin.setValue(0.0)
        self._frame_width_spin.setFixedWidth(100)
        self._frame_width_spin.valueChanged.connect(self._on_frame_width_changed)
        width_unit_label = QLabel("cm frame width")
        width_unit_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 12px;")
        width_row.addWidget(self._frame_width_spin)
        width_row.addWidget(width_unit_label)
        width_row.addStretch()
        layout.addLayout(width_row, row, 1)
        row += 1

        # Explanation of the computed relationship
        self._scale_hint_label = QLabel("")
        self._scale_hint_label.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 11px;")
        self._scale_hint_label.setWordWrap(True)
        layout.addWidget(self._scale_hint_label, row, 0, 1, 2)

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

        stop_hint = QLabel("Press  q  or click Stop to end the recording")
        stop_hint.setStyleSheet(f"color: {COLOUR['text_dim']}; font-size: 11px;")
        stop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(stop_hint)

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

    def _ensure_save_dir_usable(self) -> None:
        """
        Make sure the save directory exists and is writable at startup.

        Creates it if missing. If it cannot be used at all — typically a path
        left over from another machine, pointing at a different user's home —
        falls back to the current user's default and says so, rather than
        leaving a broken path in the field for the user to discover when they
        press Start.
        """
        save_dir = Path(self._save_dir_edit.text()).expanduser()

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            if os.access(save_dir, os.W_OK):
                self._save_dir_edit.setText(str(save_dir))
                return
        except OSError:
            pass   # fall through to the fallback below

        fallback_dir = Path(DEFAULT_SAVE_DIR)
        try:
            fallback_dir.mkdir(parents=True, exist_ok=True)
            self._save_dir_edit.setText(str(fallback_dir))
            self._bottom_status.setText(
                f"Save directory '{save_dir}' is not usable — "
                f"switched to {fallback_dir}"
            )
        except OSError:
            # Even the fallback failed; leave the field alone and let the
            # pre-recording validation produce a clear message.
            self._bottom_status.setText(
                f"Warning: save directory '{save_dir}' is not usable"
            )

    def _refresh_free_space(self) -> None:
        """
        Update the cached free-space figure for the current save directory.

        Never raises. The save directory comes from a config file or a text
        field, so it may be missing, unreadable, or on an unmounted drive —
        none of which should stop the app from starting. Free space is only
        used to estimate maximum recording time, so falling back to None
        simply hides that estimate.
        """
        try:
            save_dir = Path(self._save_dir_edit.text()).expanduser()
            self._free_space_gb = (
                get_free_space_gb(save_dir) if save_dir.is_dir() else None
            )
        except (OSError, ValueError):
            # PermissionError (another user's home), FileNotFoundError,
            # unmounted network path, malformed path string
            self._free_space_gb = None

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

        # Clamp the fps field to the new mode's ceiling BEFORE switching modes,
        # so set_mode() (which restarts the preview) picks up the correct
        # target fps rather than a stale one from the previous mode.
        self._fps_spin.blockSignals(True)
        self._fps_spin.setMaximum(mode.max_fps)
        if self._fps_spin.value() > mode.max_fps:
            self._fps_spin.setValue(mode.max_fps)
        elif self._fps_spin.value() <= 0.1:
            self._fps_spin.setValue(mode.max_fps)
        self._fps_spin.blockSignals(False)
        self._fps_max_label.setText(f"max {mode.max_fps:.1f}")

        self._camera.set_capture_fps(self._fps_spin.value())
        self._camera.set_mode(mode)   # restarts preview; applies target fps on start

        # Frame geometry changed — a zoom region from the old mode is no
        # longer meaningful, so return to the full view
        if hasattr(self, "_preview_widget"):
            self._preview_widget.reset_view()

        # Field of view and/or pixel count changed — recompute the scale from
        # the stored full-sensor calibration so it stays physically correct
        if hasattr(self, "_scale_px_radio"):
            self._rescale_for_new_sensor_mode()

        self._refresh_headroom()

    def _on_fps_changed(self, value: float) -> None:
        self._camera.set_capture_fps(value)
        self._refresh_headroom()

    # ── Scale: px/cm and frame width are two views of the same number ─────────

    def _on_scale_mode_changed(self, _checked: bool = False) -> None:
        """
        Enable whichever scale field the user chose to enter, disable the other.
        The disabled one is not empty — it shows the value derived from the
        entered one, so both are always visible and consistent.
        """
        px_is_authoritative = self._scale_px_radio.isChecked()
        self._px_per_cm_spin.setEnabled(px_is_authoritative)
        self._frame_width_spin.setEnabled(not px_is_authoritative)
        self._recompute_derived_scale()

    def _on_px_per_cm_changed(self, _value: float) -> None:
        if self._scale_px_radio.isChecked():
            self._recompute_derived_scale()

    def _on_frame_width_changed(self, _value: float) -> None:
        if self._scale_width_radio.isChecked():
            self._recompute_derived_scale()

    def _recompute_derived_scale(self) -> None:
        """
        Derive the non-authoritative scale value from the authoritative one.

        The calibration is anchored to the PHYSICAL scene, not the pixel
        count, because these vary independently across sensor modes:

          · 4056×3040 and 2028×1520 see the same scene (both full sensor).
            Switching between them halves px_per_cm but leaves the frame's
            physical width unchanged.
          · 1332×990 reads only the central 66% of the sensor, so it sees a
            physically narrower scene at the same optical setup.

        We therefore store the calibration internally as the scene width the
        FULL sensor would see (`_full_fov_width_cm`), and derive both
        displayed values from it for whichever mode is active.
        """
        mode           = self._current_sensor_mode()
        frame_width_px = mode.width
        fov_fraction   = mode.fov_fraction_width

        if self._scale_px_radio.isChecked():
            px_per_cm = self._px_per_cm_spin.value()
            if px_per_cm > 0:
                frame_width_cm          = frame_width_px / px_per_cm
                self._full_fov_width_cm = frame_width_cm / fov_fraction
            else:
                frame_width_cm          = 0.0
                self._full_fov_width_cm = None
            self._frame_width_spin.blockSignals(True)
            self._frame_width_spin.setValue(frame_width_cm)
            self._frame_width_spin.blockSignals(False)
        else:
            frame_width_cm = self._frame_width_spin.value()
            if frame_width_cm > 0:
                px_per_cm               = frame_width_px / frame_width_cm
                self._full_fov_width_cm = frame_width_cm / fov_fraction
            else:
                px_per_cm               = 0.0
                self._full_fov_width_cm = None
            self._px_per_cm_spin.blockSignals(True)
            self._px_per_cm_spin.setValue(px_per_cm)
            self._px_per_cm_spin.blockSignals(False)

        self._update_scale_hint(mode)

    def _rescale_for_new_sensor_mode(self) -> None:
        """
        Called when the sensor mode changes. Recomputes both scale values
        from the stored full-sensor calibration, so an existing calibration
        stays physically correct across mode changes rather than being
        silently reinterpreted.
        """
        mode = self._current_sensor_mode()

        if self._full_fov_width_cm is None:
            self._update_scale_hint(mode)
            return

        frame_width_cm = self._full_fov_width_cm * mode.fov_fraction_width
        px_per_cm      = mode.width / frame_width_cm if frame_width_cm > 0 else 0.0

        self._frame_width_spin.blockSignals(True)
        self._px_per_cm_spin.blockSignals(True)
        self._frame_width_spin.setValue(frame_width_cm)
        self._px_per_cm_spin.setValue(px_per_cm)
        self._frame_width_spin.blockSignals(False)
        self._px_per_cm_spin.blockSignals(False)

        self._update_scale_hint(mode)

    def _update_scale_hint(self, mode) -> None:
        """Explain what the current numbers mean for the active sensor mode."""
        if self._px_per_cm_spin.value() <= 0:
            self._scale_hint_label.setText(
                "Enter a value to set the spatial scale (optional)."
            )
            return

        if mode.is_full_fov:
            fov_note = "full sensor field of view"
        else:
            fov_note = (
                f"cropped field of view — this mode sees "
                f"{mode.fov_fraction_width * 100:.0f}% of the scene width"
            )
        self._scale_hint_label.setText(
            f"{mode.width} px across {self._frame_width_spin.value():.1f} cm "
            f"({fov_note}). Recalculated automatically when the sensor mode changes."
        )

    def _on_colour_mode_changed(self, _index: int) -> None:
        self._camera.set_colour_mode(self._current_channels())
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

    def _collect_recording_settings(self) -> RecordingSettings:
        """Assemble a RecordingSettings object from the current form state."""
        mode = self._current_sensor_mode()

        px_per_cm      = self._px_per_cm_spin.value()
        frame_width_cm = self._frame_width_spin.value()
        # Zero means "not set" — both fields are kept in sync, so if one is
        # unset the other is too.
        px_per_cm      = None if px_per_cm      <= 0 else round(px_per_cm, 1)
        frame_width_cm = None if frame_width_cm <= 0 else round(frame_width_cm, 1)

        metadata_values = dict(self._field_list.get_field_values())
        metadata_values["experimenter"]   = self._experimenter_edit.text()
        metadata_values["treatments"]     = self._field_list.get_treatments()
        metadata_values["field_order"]    = self._field_list.get_order()
        metadata_values["px_per_cm"]      = px_per_cm
        metadata_values["frame_width_cm"] = frame_width_cm
        metadata_values["scale_entered_as"] = (
            "px_per_cm" if self._scale_px_radio.isChecked() else "frame_width_cm"
        )

        return RecordingSettings(
            save_dir     = Path(self._save_dir_edit.text()),
            file_name    = self._file_name_edit.text().strip() or "recording",
            folder_name  = self._folder_name_edit.text().strip() or "images",
            format_label = self._format_combo.currentText(),
            frame_width  = mode.width,
            frame_height = mode.height,
            fps          = self._fps_spin.value(),
            channels     = self._current_channels(),
            duration_s   = None if self._duration_check.isChecked()
                           else float(self._duration_spin.value()),
            fov_fraction = mode.fov_fraction_width,
            metadata     = metadata_values,
        )

    def _start_recording(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        settings = self._collect_recording_settings()

        # ── Validation ─────────────────────────────────────────────────────────
        # Checked explicitly rather than letting the recording fail on the first
        # write: a clear message before starting is far better than discovering
        # the problem after the animals have been running for ten minutes.
        try:
            if not settings.save_dir.is_dir():
                QMessageBox.warning(
                    self, "Save directory not found",
                    f"This directory does not exist:\n{settings.save_dir}\n\n"
                    f"Choose another with the folder button, or create it first."
                )
                return
            if not os.access(settings.save_dir, os.W_OK):
                QMessageBox.warning(
                    self, "Save directory not writable",
                    f"You do not have permission to write to:\n"
                    f"{settings.save_dir}\n\n"
                    f"Choose a directory inside your own home folder."
                )
                return
        except OSError as path_error:
            QMessageBox.warning(
                self, "Save directory unusable",
                f"Could not use this directory:\n{settings.save_dir}\n\n"
                f"{path_error}"
            )
            return

        target = settings.output_dir if settings.is_image_stack else settings.video_file
        try:
            target_exists = target.exists()
        except OSError:
            target_exists = False
        if target_exists:
            overwrite = QMessageBox.question(
                self, "Overwrite existing output?",
                f"This already exists:\n{target}\n\nOverwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return

        # ── Start ──────────────────────────────────────────────────────────────
        try:
            # Stop the preview THREAD before recording. Both it and the record
            # loop would otherwise call capture_array() on the same camera, and
            # each call consumes one request — so they would take alternate
            # frames and the recording would run at half the requested rate.
            # The session serves the preview from its own capture request.
            self._camera.pause_preview()

            preview_callback = (
                (lambda frame: self.frame_ready.emit(frame))
                if self._show_preview_check.isChecked() else None
            )
            self._session = RecordingSession(
                self._camera, settings,
                preview_callback = preview_callback,
                preview_fps      = min(10.0, settings.fps),
            )
            self._session.start()
        except Exception as start_error:
            QMessageBox.critical(
                self, "Could not start recording", str(start_error)
            )
            self._session = None
            try:
                self._camera.resume_preview()
            except Exception:
                pass
            return

        self._recording_settings = settings
        self._is_recording       = True

        self._setup_panel.setVisible(False)
        self._status_panel.setVisible(True)
        self._record_button.setText("■  Stop recording")
        self._record_button.setStyleSheet(
            f"background-color: {COLOUR['button_stop']}; color: white; "
            f"font-size: 14px; font-weight: bold; border-radius: 4px; border: none;"
        )
        self._bottom_status.setText(f"Recording to {target.name}")
        self._warning_label.setText("")

        # Poll the session for live stats
        self._status_timer.start(250)

    def _stop_recording(self) -> None:
        """
        Ask the recording to stop, then hand over to the status timer.

        Does NOT block. Capture stops immediately, but frames already buffered
        still have to be written, which can take several seconds after a long
        high-rate recording. The timer keeps polling and shows that progress,
        so the window stays responsive instead of appearing to hang.
        """
        if self._session is None:
            self._reset_ui_after_recording()
            return

        self._session.request_stop()
        self._is_finishing = True

        self._record_button.setEnabled(False)
        self._record_button.setText("Finishing…")
        self._record_button.setStyleSheet(
            f"background-color: {COLOUR['panel']}; color: {COLOUR['text_dim']}; "
            f"font-size: 14px; font-weight: bold; border-radius: 4px; border: none;"
        )
        self._warning_label.setStyleSheet(f"color: {COLOUR['amber']}; font-size: 12px;")
        self._warning_label.setText("Writing buffered frames — do not close the app.")
        # Poll faster while draining so the countdown looks responsive
        self._status_timer.start(100)

    def _finish_recording(self) -> None:
        """Called once the writer has drained the buffer. Safe to block now."""
        from PyQt6.QtWidgets import QMessageBox

        self._status_timer.stop()
        self._is_finishing = False

        capture_summary = self._session.finalize() if self._session else {}

        # ── Write the metadata sidecar ─────────────────────────────────────────
        if self._recording_settings is not None:
            try:
                metadata_dict = build_metadata(self._recording_settings, capture_summary)
                write_metadata(metadata_dict, self._recording_settings.metadata_file)
            except Exception as metadata_error:
                QMessageBox.warning(
                    self, "Metadata not saved",
                    f"The recording completed but the metadata file could not "
                    f"be written:\n{metadata_error}"
                )

        self._session = None
        self._reset_ui_after_recording()

        # ── Summarise ──────────────────────────────────────────────────────────
        frames_written = capture_summary.get("frames_written", 0)
        frames_dropped = capture_summary.get("frames_dropped", 0)
        frames_missed  = capture_summary.get("frames_missed", 0)
        duration_s     = capture_summary.get("actual_duration_s", 0.0)
        effective_fps  = capture_summary.get("effective_fps", 0.0)
        requested_fps  = capture_summary.get("requested_fps", 0.0)
        shortfall_pct  = capture_summary.get("fps_shortfall_pct", 0.0)

        self._bottom_status.setText(
            f"Saved {frames_written} frames in {duration_s:.1f} s "
            f"({effective_fps:.1f} fps, {frames_dropped} dropped, "
            f"{frames_missed} missed)"
        )

        # A rate shortfall is easy to miss and corrupts any speed measured from
        # the video, so say so explicitly rather than only in the metadata.
        if shortfall_pct >= 10.0 and requested_fps > 0:
            QMessageBox.warning(
                self, "Recorded slower than requested",
                f"You requested {requested_fps:.1f} fps but the camera "
                f"sustained {effective_fps:.1f} fps "
                f"({shortfall_pct:.0f}% short).\n\n"
                f"The frames themselves are fine, but the video's header "
                f"stores the requested rate, so playing it back or measuring "
                f"speed from frame numbers alone would be wrong by that "
                f"factor.\n\n"
                f"Exact per-frame times were written to:\n"
                f"{Path(capture_summary.get('frame_times_file') or '—').name}\n\n"
                f"For future recordings, lower the framerate or the resolution "
                f"until this warning stops appearing."
            )

        if capture_summary.get("error"):
            QMessageBox.critical(
                self, "Recording error",
                f"The recording stopped because of an error:\n\n"
                f"{capture_summary['error']}"
            )

        # Update the ✓ marks now that a new file exists, then advance to the
        # next planned session so the experimenter can start the next trial
        # without touching the metadata fields.
        self._refresh_list_recorded_marks()
        if self._metadata_rows and not capture_summary.get("error"):
            current_index = self._list_combo.currentIndex()
            if current_index < len(self._metadata_rows) - 1:
                self._list_combo.setCurrentIndex(current_index + 1)
            else:
                self._bottom_status.setText(
                    self._bottom_status.text() + "   —   end of metadata list"
                )

    def _reset_ui_after_recording(self) -> None:
        """Return the window to its pre-recording state."""
        # Hand the preview back to its own thread now the record loop is done
        try:
            if self._show_preview_check.isChecked():
                self._camera.resume_preview()
        except Exception:
            pass
        self._is_recording = False
        self._is_finishing = False
        self._setup_panel.setVisible(True)
        self._status_panel.setVisible(False)
        self._warning_label.setText("")
        self._record_button.setEnabled(True)
        self._record_button.setText("▶  Start recording")
        self._record_button.setStyleSheet(
            f"background-color: {COLOUR['button_start']}; color: white; "
            f"font-size: 14px; font-weight: bold; border-radius: 4px; border: none;"
        )

    # ── Live status updates during recording ───────────────────────────────────

    def _update_recording_status(self) -> None:
        """Called by a QTimer while recording; refreshes the status panel."""
        if self._session is None:
            return

        # ── Finishing: capture has stopped, buffer is still being written ──────
        if self._is_finishing:
            if self._session.is_finished:
                self._finish_recording()
            else:
                remaining = self._session.frames_remaining
                self._warning_label.setText(
                    f"Writing buffered frames — {remaining} left. "
                    f"Do not close the app."
                )
                self._frames_label.setText(f"{self._session.stats.frames_written:7d}")
                self._headroom_live_label.setText(f"{remaining:5d} queued")
                self._headroom_live_label.setStyleSheet(f"color: {COLOUR['amber']};")
            return

        stats = self._session.stats

        self._elapsed_label.setText(f"{stats.elapsed_s:7.1f} s")
        self._frames_label.setText(f"{stats.frames_written:7d}")
        self._dropped_label.setText(
            f"{stats.frames_dropped:7d}  ({stats.drop_rate_pct:.1f}%)"
        )
        # Live capture rate: the number that reveals a rate shortfall while
        # there is still time to do something about it
        if stats.elapsed_s > 0.5:
            live_fps = stats.frames_captured / stats.elapsed_s
            requested_fps = self._recording_settings.fps if self._recording_settings else 0
            self._elapsed_label.setText(
                f"{stats.elapsed_s:7.1f} s   @ {live_fps:.1f} fps"
            )
            if requested_fps > 0 and live_fps < requested_fps * 0.9:
                self._elapsed_label.setStyleSheet(f"color: {COLOUR['red']};")
            else:
                self._elapsed_label.setStyleSheet(f"color: {COLOUR['accent']};")

        # Queue depth is the live indicator of whether the disk is keeping up
        queue_pct = min(100, int(100 * stats.queue_depth / 60))
        self._headroom_live_label.setText(f"queue {queue_pct:3d}% full")
        if queue_pct > 80:
            queue_colour = COLOUR["red"]
        elif queue_pct > 50:
            queue_colour = COLOUR["amber"]
        else:
            queue_colour = COLOUR["green"]
        self._headroom_live_label.setStyleSheet(f"color: {queue_colour};")

        # ── Warnings with concrete suggestions ─────────────────────────────────
        self._update_drop_warning(stats)

        # Auto-stop once the capture thread has finished a fixed-duration run
        if not self._session.is_running:
            self._stop_recording()

    def _update_drop_warning(self, stats) -> None:
        """
        Warn about the two distinct failure modes, which need different fixes.

        MISSED frames mean the camera could not deliver at the requested rate,
        so the recording is slower than it claims — the serious case, because
        nothing about the file reveals it.

        DROPPED frames mean the disk could not keep up with frames that were
        successfully captured.
        """
        requested_fps = self._recording_settings.fps if self._recording_settings else 0

        # ── Rate shortfall (missed frames) ─────────────────────────────────────
        if stats.frames_missed > 0 and stats.miss_rate_pct >= 5.0:
            live_fps = (stats.frames_captured / stats.elapsed_s
                        if stats.elapsed_s > 0 else 0)
            self._warning_label.setStyleSheet(f"color: {COLOUR['red']}; font-size: 12px;")
            self._warning_label.setText(
                f"✖ Capturing at {live_fps:.1f} fps, not the requested "
                f"{requested_fps:.1f} ({stats.miss_rate_pct:.0f}% of frames missed).\n\n"
                f"The camera cannot sustain this rate at this resolution. "
                f"Stop and lower the framerate or the resolution — the video's "
                f"timestamps will be correct either way, but the file will be "
                f"shorter than expected."
            )
            return

        # ── Disk shortfall (dropped frames) ────────────────────────────────────
        if stats.frames_dropped == 0:
            self._warning_label.setText("")
            return

        drop_rate = stats.drop_rate_pct
        if drop_rate < 1.0:
            self._warning_label.setStyleSheet(f"color: {COLOUR['amber']}; font-size: 12px;")
            self._warning_label.setText(
                f"⚠ {stats.frames_dropped} frames dropped ({drop_rate:.1f}%). "
                f"Occasional drops at this rate are usually tolerable for tracking."
            )
            return

        suggestions = []
        if self._current_channels() == 3:
            suggestions.append("switch to Greyscale (~3× less data)")
        if self._fps_spin.value() > 5:
            suggestions.append("lower the framerate")
        if self._format_combo.currentText() != "H.264 video (.mp4)":
            suggestions.append("use H.264 (much smaller, though less ideal for tracking)")
        suggestions.append("choose a lower resolution")

        self._warning_label.setStyleSheet(f"color: {COLOUR['red']}; font-size: 12px;")
        self._warning_label.setText(
            f"✖ {stats.frames_dropped} frames dropped ({drop_rate:.1f}%) — "
            f"the SD card cannot keep up.\n\n"
            f"Stop and try: {'; '.join(suggestions[:3])}."
        )

    # =========================================================================
    # Profiles, settings, and shared UI helpers
    # =========================================================================

    def _on_load_profile(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        profile_file, _ = QFileDialog.getOpenFileName(
            self, "Load profile", self._save_dir_edit.text(), "YAML files (*.yaml *.yml)"
        )
        if not profile_file:
            return

        try:
            loaded_profile = load_profile(Path(profile_file))
        except Exception as load_error:
            QMessageBox.critical(
                self, "Could not read profile",
                f"The file could not be read as YAML:\n\n{load_error}"
            )
            return

        if not isinstance(loaded_profile, dict):
            QMessageBox.warning(
                self, "Not a profile file",
                "This YAML file does not contain a profile."
            )
            return

        # A profile must have at least one of the three expected sections.
        # Without this check, loading the wrong YAML (a metadata sidecar, or
        # config_app.yaml) silently does nothing, which looks like a bug.
        expected_sections = {"recording", "camera", "metadata"}
        if not expected_sections.intersection(loaded_profile.keys()):
            QMessageBox.warning(
                self, "Not a profile file",
                f"This YAML file has no profile sections.\n\n"
                f"Expected at least one of: {', '.join(sorted(expected_sections))}\n"
                f"Found: {', '.join(sorted(loaded_profile.keys())) or '(empty file)'}\n\n"
                f"Recording metadata files and config_app.yaml are not profiles."
            )
            return

        self._profile = loaded_profile
        self._apply_profile_to_ui()
        self._bottom_status.setText(f"Loaded profile: {Path(profile_file).name}")

    def _on_save_profile(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        profile_file, _ = QFileDialog.getSaveFileName(
            self, "Save profile", self._save_dir_edit.text(), "YAML files (*.yaml *.yml)"
        )
        if not profile_file:
            return

        # Ensure the file has a .yaml suffix, otherwise it won't appear in the
        # load dialog's filter later
        profile_path = Path(profile_file)
        if profile_path.suffix.lower() not in (".yaml", ".yml"):
            profile_path = profile_path.with_suffix(".yaml")

        try:
            save_profile(self._collect_profile_from_ui(), profile_path)
            self._bottom_status.setText(f"Saved profile: {profile_path.name}")
        except Exception as save_error:
            QMessageBox.critical(
                self, "Could not save profile", str(save_error)
            )

    def _on_recalibrate_write_speed(self) -> None:
        from benchmark import measure_write_speed_mbs
        from PyQt6.QtWidgets import QMessageBox

        save_dir = Path(self._save_dir_edit.text()).expanduser()

        # The benchmark writes a large temporary file, so the directory must
        # exist and be writable. Check first rather than failing mid-write.
        try:
            if not save_dir.is_dir():
                QMessageBox.warning(
                    self, "Save directory not found",
                    f"This directory does not exist:\n{save_dir}"
                )
                return
            if not os.access(save_dir, os.W_OK):
                QMessageBox.warning(
                    self, "Save directory not writable",
                    f"You do not have permission to write to:\n{save_dir}\n\n"
                    f"Choose a directory inside your own home folder."
                )
                return
        except OSError as path_error:
            QMessageBox.warning(self, "Save directory unusable", str(path_error))
            return

        self._bottom_status.setText(
            "Measuring write speed… (writes a 400 MB test file, ~15 s)"
        )
        QApplication.processEvents()

        try:
            write_speed_mbs = measure_write_speed_mbs(save_dir)
        except OSError as benchmark_error:
            QMessageBox.critical(
                self, "Write speed test failed",
                f"Could not complete the test:\n\n{benchmark_error}\n\n"
                f"The disk may be full — the test needs 400 MB free."
            )
            self._bottom_status.setText("Write speed test failed")
            return

        from datetime import date
        self._app_config["hardware"]["sd_write_speed_mbs"] = write_speed_mbs
        self._app_config["hardware"]["sd_write_speed_measured_date"] = str(date.today())
        save_app_config(self._app_config)
        self._refresh_free_space()
        self._refresh_headroom()
        self._bottom_status.setText(
            f"Write speed: {write_speed_mbs:.1f} MB/s  (calibrated today)"
        )

    # =========================================================================
    # Profile helpers
    # =========================================================================

    def _collect_profile_from_ui(self) -> dict:
        return {
            "recording": {
                "save_dir":      self._save_dir_edit.text(),
                "output_format": self._format_combo.currentText(),
                "duration_s":    None if self._duration_check.isChecked() else self._duration_spin.value(),
                "base_name":      self._file_name_edit.text(),
                "auto_file_name": self._auto_name_check.isChecked(),
                "folder_name":   self._folder_name_edit.text(),
            },
            "camera": {
                "sensor_mode": self._sensor_mode_combo.currentIndex(),
                "fps":         self._fps_spin.value(),
                "colour_mode": self._colour_combo.currentText(),
            },
            "metadata": {
                **self._field_list.get_field_values(),
                "experimenter":     self._experimenter_edit.text(),
            } | {
                "treatments":       self._field_list.get_treatments(),
                "field_order":      self._field_list.get_order(),
                "px_per_cm":        self._px_per_cm_spin.value() or None,
                "frame_width_cm":   self._frame_width_spin.value() or None,
                "scale_entered_as": ("px_per_cm" if self._scale_px_radio.isChecked()
                                     else "frame_width_cm"),
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
        if "auto_file_name" in rec:
            self._auto_name_check.setChecked(bool(rec["auto_file_name"]))
        if "base_name" in rec and not self._auto_name_check.isChecked():
            self._file_name_edit.setText(rec["base_name"])
        if "folder_name"   in rec: self._folder_name_edit.setText(rec["folder_name"])
        if "duration_s"    in rec:
            if rec["duration_s"] is None:
                self._duration_check.setChecked(True)
            else:
                self._duration_check.setChecked(False)
                self._duration_spin.setValue(int(rec["duration_s"]))

        if "experimenter" in meta:
            self._experimenter_edit.setText(str(meta["experimenter"]))
        for field_key, _label in FILENAME_FIELDS:
            if field_key in meta:
                self._field_list.set_field_value(field_key, str(meta[field_key]))

        if "treatments" in meta and isinstance(meta["treatments"], dict):
            self._field_list.set_treatments(meta["treatments"])

        # Row order must be applied after the treatments exist, since the saved
        # order refers to them
        if "field_order" in meta and isinstance(meta["field_order"], list):
            self._apply_field_order(meta["field_order"])

        # Restore the scale: set the mode first, then the authoritative value,
        # which recomputes the derived one automatically.
        scale_mode = meta.get("scale_entered_as", "px_per_cm")
        if scale_mode == "frame_width_cm":
            self._scale_width_radio.setChecked(True)
            if meta.get("frame_width_cm"):
                self._frame_width_spin.setValue(float(meta["frame_width_cm"]))
        else:
            self._scale_px_radio.setChecked(True)
            if meta.get("px_per_cm"):
                self._px_per_cm_spin.setValue(float(meta["px_per_cm"]))

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
    # Automatic file naming from metadata
    # =========================================================================


    # =========================================================================
    # Automatic file naming from metadata
    # =========================================================================

    def _on_treatment_names_toggled(self, checked: bool) -> None:
        """Switch between 'high-dim' and 'density-high-light-dim' naming."""
        self._app_config["app"]["include_treatment_names"] = checked
        save_app_config(self._app_config)
        self._refresh_auto_file_name()

    def _on_auto_name_toggled(self, _state: int) -> None:
        is_auto = self._auto_name_check.isChecked()
        self._file_name_edit.setReadOnly(is_auto)
        self._file_name_edit.setEnabled(not is_auto)
        if is_auto:
            self._refresh_auto_file_name()

    def _refresh_auto_file_name(self) -> None:
        """Rebuild the file name from metadata, if auto-naming is active."""
        if not hasattr(self, "_auto_name_check"):
            return
        if not self._auto_name_check.isChecked():
            return

        include_names = self._app_config["app"].get("include_treatment_names", False)
        auto_name = build_auto_file_name(
            components              = self._field_list.get_components(),
            include_treatment_names = include_names,
        )
        self._file_name_edit.setText(auto_name)

        # A changed name changes which outputs already exist
        self._refresh_list_recorded_marks()

    # =========================================================================
    # Metadata list (CSV) loading and navigation
    # =========================================================================

    def _on_load_metadata_list(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        csv_file, _ = QFileDialog.getOpenFileName(
            self, "Load metadata list", self._save_dir_edit.text(),
            "CSV files (*.csv);;All files (*)"
        )
        if not csv_file:
            return

        try:
            rows, warnings = load_metadata_list(Path(csv_file))
        except Exception as load_error:
            QMessageBox.critical(
                self, "Could not read metadata list",
                f"{load_error}\n\n"
                f"The file needs a header row. Reserved column names are "
                f"experimenter, experiment and trial; every other column is "
                f"treated as a treatment."
            )
            return

        self._metadata_rows      = rows
        self._metadata_list_file = Path(csv_file)

        self._list_combo.blockSignals(True)
        self._list_combo.clear()
        for row in rows:
            self._list_combo.addItem(row.summary())
        self._list_combo.blockSignals(False)

        self._list_nav_widget.setVisible(True)
        self._list_combo.setCurrentIndex(0)
        self._apply_metadata_row(0)
        self._refresh_list_recorded_marks()

        message = f"Loaded {len(rows)} rows from {Path(csv_file).name}"
        if warnings:
            message += "  —  " + "; ".join(warnings)
        self._bottom_status.setText(message)

    def _on_clear_metadata_list(self) -> None:
        """Close the list; metadata fields stay as they are and become manual."""
        self._metadata_rows      = []
        self._metadata_list_file = None
        self._list_combo.blockSignals(True)
        self._list_combo.clear()
        self._list_combo.blockSignals(False)
        self._list_nav_widget.setVisible(False)
        self._bottom_status.setText("Metadata list closed — fields are manual again")

    def _on_list_row_selected(self, index: int) -> None:
        if 0 <= index < len(self._metadata_rows):
            self._apply_metadata_row(index)

    def _step_metadata_list(self, step: int) -> None:
        """Move by step rows, clamped to the ends of the list."""
        if not self._metadata_rows:
            return
        new_index = self._list_combo.currentIndex() + step
        new_index = max(0, min(new_index, len(self._metadata_rows) - 1))
        self._list_combo.setCurrentIndex(new_index)

    def _apply_metadata_row(self, index: int) -> None:
        """Populate the metadata fields from one row of the loaded list."""
        if not (0 <= index < len(self._metadata_rows)):
            return
        row = self._metadata_rows[index]

        self._experimenter_edit.setText(row.experimenter)
        self._field_list.set_field_value("experiment", row.experiment)
        self._field_list.set_field_value("ant_id",     row.ant_id)
        self._field_list.set_field_value("trial",      row.trial)
        self._field_list.set_treatments(row.treatments)

        self._refresh_auto_file_name()

    def _components_for_row(self, row, field_order: list) -> list:
        """
        Build ordered (kind, name, value) components for a metadata-list row,
        following the current field order.

        Used for the dropdown's checkmarks, which must predict the file name a
        row WOULD produce without loading it into the fields first.
        """
        field_values = {
            "experiment": row.experiment,
            "ant_id":     row.ant_id,
            "trial":      row.trial,
        }
        treatment_items = list(row.treatments.items())
        treatment_index = 0
        components = []
        for key in field_order:
            if key == "treatment":
                if treatment_index < len(treatment_items):
                    name, value = treatment_items[treatment_index]
                    components.append(("treatment", name, value))
                    treatment_index += 1
            else:
                components.append(("field", key, field_values.get(key, "")))
        # Any treatments beyond the number of treatment slots in the current
        # order (this row has more than the loaded one did) go at the end
        for name, value in treatment_items[treatment_index:]:
            components.append(("treatment", name, value))
        return components

    def _apply_field_order(self, field_order: list) -> None:
        """
        Reorder the field list to match a saved order.

        Rows are matched by key; anything in the saved order that no longer
        exists is skipped, and anything present but unmentioned is left at the
        end. This keeps an old profile usable after the field set changes.
        """
        rows = self._field_list.rows()
        remaining = list(rows)
        ordered = []
        for key in field_order:
            for row in list(remaining):
                row_key = (row.field_key if isinstance(row, FixedFieldRow)
                           else "treatment")
                if row_key == key:
                    ordered.append(row)
                    remaining.remove(row)
                    break
        ordered.extend(remaining)

        # Rebuild the list in the new order, moving the existing widgets
        self._field_list.blockSignals(True)
        states = []
        for row in ordered:
            if isinstance(row, FixedFieldRow):
                states.append(("field", row.field_key, row.value_edit.text(), ""))
            else:
                _, name, value = row.get_component()
                states.append(("treatment", "", value, name))
        self._field_list.clear()
        for kind, field_key, value, name in states:
            if kind == "field":
                label = next((lbl for key, lbl in FILENAME_FIELDS if key == field_key),
                             field_key)
                self._field_list.add_field(field_key, label, value)
            else:
                self._field_list.add_treatment(name, value)
        self._field_list.blockSignals(False)
        self._refresh_auto_file_name()

    def _refresh_list_recorded_marks(self) -> None:
        """
        Mark rows in the dropdown whose output file already exists, so it is
        obvious at a glance which sessions still need recording.

        This only works while auto-naming is on, because otherwise there is
        no way to know which file a given row would produce.
        """
        if not self._metadata_rows or not hasattr(self, "_list_combo"):
            return
        if not self._auto_name_check.isChecked():
            return

        save_dir      = Path(self._save_dir_edit.text())
        include_names = self._app_config["app"].get("include_treatment_names", False)
        format_label  = self._format_combo.currentText()
        is_stack      = "stack" in format_label.lower()
        extension     = next(
            (ext for label, ext, _ in OUTPUT_FORMATS if label == format_label), ".avi"
        )

        current_index = self._list_combo.currentIndex()
        self._list_combo.blockSignals(True)
        field_order = self._field_list.get_order()
        for index, row in enumerate(self._metadata_rows):
            file_name = build_auto_file_name(
                self._components_for_row(row, field_order), include_names
            )
            target = (save_dir / file_name) if is_stack \
                else (save_dir / f"{file_name}{extension}")
            try:
                already_recorded = target.exists()
            except OSError:
                # Unreadable or unmounted save directory — show no mark rather
                # than breaking navigation through the list
                already_recorded = False
            mark = "✓  " if already_recorded else "     "
            self._list_combo.setItemText(index, f"{mark}{row.summary()}")
        self._list_combo.setCurrentIndex(current_index)
        self._list_combo.blockSignals(False)

    def keyPressEvent(self, event) -> None:
        """
        `q` stops an in-progress recording.
        Left/Right arrows step through the metadata list — but only when the
        focus isn't in a text field, so arrow keys still move the cursor
        normally while editing.
        """
        key = event.key()

        if key == Qt.Key.Key_Q and self._is_recording:
            self._stop_recording()
            return

        # R starts a recording, but only when not typing in a field — otherwise
        # every "r" in an experiment name would start one.
        if key == Qt.Key.Key_R and not self._is_recording:
            focus_widget = QApplication.focusWidget()
            if not isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox)):
                self._start_recording()
                return

        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self._metadata_rows:
            focus_widget = QApplication.focusWidget()
            is_editing   = isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox))
            if not is_editing:
                self._step_metadata_list(-1 if key == Qt.Key.Key_Left else +1)
                return

        super().keyPressEvent(event)

    # =========================================================================
    # Cleanup
    # =========================================================================

    def closeEvent(self, event) -> None:
        # Finish any in-progress recording so the file and metadata are valid.
        # Blocking is correct here — the window is closing anyway, and losing
        # buffered frames would corrupt the output.
        if self._is_recording or self._is_finishing:
            self._status_timer.stop()
            if self._session is not None:
                self._session.request_stop()
                while not self._session.is_finished:
                    QApplication.processEvents()
                    time.sleep(0.05)
                self._finish_recording()
        self._camera.release()
        super().closeEvent(event)
