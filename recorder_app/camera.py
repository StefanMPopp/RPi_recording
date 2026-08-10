"""
camera.py
=========
Wraps picamera2 for the recorder app.

Responsibilities:
  - Enumerate available sensor modes (resolution × fps) at startup
  - Provide a low-fps preview stream as numpy arrays (for the Qt widget)
  - Start / stop full-resolution capture to disk
  - Report dropped frames

Stub mode:
  If picamera2 is not available (i.e. running on a non-Pi machine for UI
  development), a StubCamera is used instead, which generates synthetic frames.
  This lets the UI be developed and tested without physical hardware.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

# ── Try to import picamera2; fall back to stub ─────────────────────────────────
try:
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder, H264Encoder
    from picamera2.outputs import FileOutput
    _PICAMERA2_AVAILABLE = True
except ImportError:
    _PICAMERA2_AVAILABLE = False


# =============================================================================
# Sensor mode dataclass
# =============================================================================

@dataclass
class SensorMode:
    """
    One available sensor mode for the attached camera.

    Note: `max_fps` is the MAXIMUM framerate this mode supports. Any lower
    framerate can be requested via the camera's FrameRate control, so the
    UI exposes a separate fps field rather than locking to this value.
    """
    index:      int
    width:      int
    height:     int
    max_fps:    float
    bit_depth:  int = 12
    display_label: str = field(init=False)

    def __post_init__(self):
        self.display_label = (
            f"{self.width} × {self.height}   (max {self.max_fps:.1f} fps)"
        )


# =============================================================================
# Real camera (picamera2)
# =============================================================================

class PiCamera:
    """
    Thin wrapper around picamera2.
    Provides a preview callback and capture-to-disk methods.
    """

    def __init__(self):
        self._camera            = Picamera2()
        self.sensor_modes       = self._enumerate_sensor_modes()
        self._active_mode       = self.sensor_modes[0]
        self._preview_callback: Callable[[np.ndarray], None] | None = None
        self._preview_thread:   threading.Thread | None = None
        self._preview_running   = False
        self.dropped_frames     = 0

    # ── Sensor modes ───────────────────────────────────────────────────────────

    def _enumerate_sensor_modes(self) -> list[SensorMode]:
        from constants import ALLOWED_BIT_DEPTHS
        raw_modes = self._camera.sensor_modes
        sensor_modes = []
        for index, mode in enumerate(raw_modes):
            size      = mode.get("size", (0, 0))
            fps_range = mode.get("fps", (0, 0))
            max_fps   = float(fps_range[1]) if isinstance(fps_range, (list, tuple)) else float(fps_range)
            bit_depth = int(mode.get("bit_depth", 12))

            # Skip bit depths we don't expose (tracking needs only 8-bit)
            if ALLOWED_BIT_DEPTHS is not None and bit_depth not in ALLOWED_BIT_DEPTHS:
                continue

            sensor_modes.append(SensorMode(
                index     = index,
                width     = size[0],
                height    = size[1],
                max_fps   = max_fps,
                bit_depth = bit_depth,
            ))

        # Fall back to all modes if filtering left nothing (unknown camera)
        if not sensor_modes:
            for index, mode in enumerate(raw_modes):
                size      = mode.get("size", (0, 0))
                fps_range = mode.get("fps", (0, 0))
                max_fps   = float(fps_range[1]) if isinstance(fps_range, (list, tuple)) else float(fps_range)
                sensor_modes.append(SensorMode(
                    index     = index,
                    width     = size[0],
                    height    = size[1],
                    max_fps   = max_fps,
                    bit_depth = int(mode.get("bit_depth", 12)),
                ))

        sensor_modes.sort(
            key=lambda m: (m.width * m.height, m.max_fps),
            reverse=True,
        )
        return sensor_modes

    def set_mode(self, mode: SensorMode) -> None:
        self._active_mode = mode

    # ── Preview ────────────────────────────────────────────────────────────────

    def start_preview(self, callback: Callable[[np.ndarray], None], fps: int = 10) -> None:
        """
        Start delivering preview frames to callback at up to fps frames/second.
        Frames are numpy arrays (RGB, uint8).

        picamera2 requires the lores stream to be YUV — it cannot be RGB.
        We capture YUV420 from lores and convert to RGB in the preview loop.
        """
        from constants import PREVIEW_WIDTH, PREVIEW_HEIGHT
        self._preview_callback = callback
        self._preview_running  = True

        preview_config = self._camera.create_preview_configuration(
            main  = {"size":   (self._active_mode.width, self._active_mode.height),
                     "format": "RGB888"},
            lores = {"size":   (PREVIEW_WIDTH, PREVIEW_HEIGHT),
                     "format": "YUV420"},   # lores must be YUV — converted below
        )
        self._camera.configure(preview_config)
        self._camera.start()

        frame_interval = 1.0 / fps
        self._preview_thread = threading.Thread(
            target = self._preview_loop,
            args   = (frame_interval,),
            daemon = True,
        )
        self._preview_thread.start()

    def _preview_loop(self, frame_interval: float) -> None:
        while self._preview_running:
            loop_start = time.perf_counter()
            try:
                yuv_frame = self._camera.capture_array("lores")
                rgb_frame = self._yuv420_to_rgb(yuv_frame)
                if self._preview_callback is not None:
                    self._preview_callback(rgb_frame)
            except Exception:
                pass
            elapsed   = time.perf_counter() - loop_start
            sleep_for = max(0.0, frame_interval - elapsed)
            time.sleep(sleep_for)

    @staticmethod
    def _yuv420_to_rgb(yuv_frame: np.ndarray) -> np.ndarray:
        """
        Convert a YUV420 numpy array (as returned by picamera2) to RGB uint8.
        picamera2 packs YUV420 as a single 2D array of height * 3/2 rows.
        Requires opencv: sudo apt install -y python3-opencv
        """
        import cv2
        # OpenCV YUV→colour conversion produces BGR by default; Qt expects RGB
        bgr_frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV420p2BGR)
        return cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)

    def stop_preview(self) -> None:
        self._preview_running = False
        if self._preview_thread:
            self._preview_thread.join(timeout=2.0)
        self._camera.stop()

    # ── Capture ────────────────────────────────────────────────────────────────

    def start_capture(self, output_path: Path, format_label: str) -> None:
        """Start recording to output_path. Format determined by format_label."""
        self.dropped_frames = 0
        # Capture configuration is wired up in record.py
        # (placeholder — implemented when record logic is added)
        raise NotImplementedError("Capture logic wired in next milestone.")

    def stop_capture(self) -> dict:
        """Stop recording and return capture statistics."""
        raise NotImplementedError("Capture logic wired in next milestone.")

    def release(self) -> None:
        self.stop_preview()
        self._camera.close()


# =============================================================================
# Stub camera (for UI development without hardware)
# =============================================================================

class StubCamera:
    """
    Generates synthetic noise frames so the UI can be developed and tested
    on any machine, without a Raspberry Pi or HQ camera attached.
    """

    def __init__(self):
        self.sensor_modes   = self._fake_sensor_modes()
        self.dropped_frames = 0
        self._preview_running = False
        self._preview_thread: threading.Thread | None = None

    def _fake_sensor_modes(self) -> list[SensorMode]:
        """Mirrors the real IMX477 8-bit mode list for UI development."""
        modes = [
            SensorMode(0, 4056, 3040, 17.39, 8),
            SensorMode(1, 4056, 2160, 24.32, 8),
            SensorMode(2, 2028, 1520, 66.38, 8),
            SensorMode(3, 2028, 1080, 92.27, 8),
            SensorMode(4, 1332,  990, 147.91, 8),
        ]
        modes.sort(key=lambda m: (m.width * m.height, m.max_fps), reverse=True)
        return modes

    def set_mode(self, mode: SensorMode) -> None:
        pass

    def start_preview(self, callback: Callable[[np.ndarray], None], fps: int = 10) -> None:
        from constants import PREVIEW_WIDTH, PREVIEW_HEIGHT
        self._preview_running = True
        frame_interval        = 1.0 / fps

        def loop():
            while self._preview_running:
                start = time.perf_counter()
                # Synthetic grey-noise frame
                frame = np.random.randint(60, 180, (PREVIEW_HEIGHT, PREVIEW_WIDTH, 3), dtype=np.uint8)
                callback(frame)
                elapsed = time.perf_counter() - start
                time.sleep(max(0.0, frame_interval - elapsed))

        self._preview_thread = threading.Thread(target=loop, daemon=True)
        self._preview_thread.start()

    def stop_preview(self) -> None:
        self._preview_running = False
        if self._preview_thread:
            self._preview_thread.join(timeout=2.0)

    def start_capture(self, output_path: Path, format_label: str) -> None:
        raise NotImplementedError("Stub camera does not capture to disk.")

    def stop_capture(self) -> dict:
        raise NotImplementedError("Stub camera does not capture to disk.")

    def release(self) -> None:
        self.stop_preview()


# =============================================================================
# Factory
# =============================================================================

def make_camera() -> PiCamera | StubCamera:
    """Return a real PiCamera if picamera2 is available, else a StubCamera."""
    if _PICAMERA2_AVAILABLE:
        return PiCamera()
    return StubCamera()
