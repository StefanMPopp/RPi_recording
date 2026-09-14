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

    Two independent properties matter here:

      Pixel count (width × height) — how many pixels the mode outputs.
      Crop region (crop_width × crop_height) — how much of the physical
      sensor area the mode actually reads, in full-sensor pixel units.

    These are independent. On the IMX477, 4056×3040 and 2028×1520 both read
    the FULL sensor (identical field of view) — the latter is simply 2×2
    binned. But 1332×990 reads only the central 2664×1980 region, so it sees
    a narrower scene.

    This distinction matters for spatial calibration: px_per_cm depends on
    pixel count, but the physical width of the scene depends on the crop.

    Note: `max_fps` is the MAXIMUM framerate this mode supports. Any lower
    framerate can be requested via the camera's FrameRate control.
    """
    index:       int
    width:       int
    height:      int
    max_fps:     float
    bit_depth:   int = 12
    crop_width:  int = 0     # sensor pixels read, 0 = unknown
    crop_height: int = 0
    sensor_full_width:  int = 0
    sensor_full_height: int = 0
    display_label: str = field(init=False)

    def __post_init__(self):
        fov_note = ""
        if self.fov_fraction_width < 0.99:
            fov_note = f"   [{self.fov_fraction_width * 100:.0f}% FoV]"
        self.display_label = (
            f"{self.width} × {self.height}   (max {self.max_fps:.1f} fps){fov_note}"
        )

    @property
    def fov_fraction_width(self) -> float:
        """
        Fraction of the sensor's full width this mode covers.
        1.0 = full field of view; 0.66 = sees 66% of the full scene width.
        """
        if self.sensor_full_width and self.crop_width:
            return self.crop_width / self.sensor_full_width
        return 1.0

    @property
    def is_full_fov(self) -> bool:
        return self.fov_fraction_width >= 0.99


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
        self._preview_fps       = 10          # display refresh rate of the UI widget
        self._target_fps:  float | None = None   # sensor FrameRate — matches recording fps
        self._preview_channels  = 3           # 1 = greyscale, 3 = colour
        self.dropped_frames     = 0

    # ── Sensor modes ───────────────────────────────────────────────────────────

    def _enumerate_sensor_modes(self) -> list[SensorMode]:
        from constants import ALLOWED_BIT_DEPTHS
        raw_modes = self._camera.sensor_modes

        # The sensor's full pixel array — the largest mode's crop region.
        # Used as the reference for computing each mode's field of view.
        sensor_full_width  = 0
        sensor_full_height = 0
        for mode in raw_modes:
            crop = mode.get("crop_limits", None)
            if crop and len(crop) == 4:
                sensor_full_width  = max(sensor_full_width,  crop[2])
                sensor_full_height = max(sensor_full_height, crop[3])

        def build_mode(index: int, mode: dict) -> SensorMode:
            size      = mode.get("size", (0, 0))
            fps_range = mode.get("fps", (0, 0))
            max_fps   = float(fps_range[1]) if isinstance(fps_range, (list, tuple)) else float(fps_range)
            crop      = mode.get("crop_limits", None)
            crop_w    = crop[2] if crop and len(crop) == 4 else 0
            crop_h    = crop[3] if crop and len(crop) == 4 else 0
            return SensorMode(
                index              = index,
                width              = size[0],
                height             = size[1],
                max_fps            = max_fps,
                bit_depth          = int(mode.get("bit_depth", 12)),
                crop_width         = crop_w,
                crop_height        = crop_h,
                sensor_full_width  = sensor_full_width,
                sensor_full_height = sensor_full_height,
            )

        sensor_modes = [
            build_mode(index, mode)
            for index, mode in enumerate(raw_modes)
            if ALLOWED_BIT_DEPTHS is None
            or int(mode.get("bit_depth", 12)) in ALLOWED_BIT_DEPTHS
        ]

        # Fall back to all modes if filtering left nothing (unknown camera)
        if not sensor_modes:
            sensor_modes = [build_mode(i, m) for i, m in enumerate(raw_modes)]

        sensor_modes.sort(
            key=lambda m: (m.width * m.height, m.max_fps),
            reverse=True,
        )
        return sensor_modes

    def set_mode(self, mode: SensorMode) -> None:
        """
        Switch to a new sensor mode. The camera's stream configuration is
        tied to the sensor mode (it determines which raw sensor mode is
        selected), so if a preview is currently running it must be stopped
        and restarted with the new configuration — simply updating
        _active_mode has no effect on a stream that's already running.
        """
        self._active_mode = mode
        if self._preview_running:
            callback = self._preview_callback
            fps      = self._preview_fps
            self.stop_preview()
            self.start_preview(callback, fps)

    def set_colour_mode(self, channels: int) -> None:
        """
        Set the preview/capture colour mode: 1 = greyscale, 3 = colour.
        Takes effect on the next frame — no stream restart needed, since
        this only changes how already-flowing YUV frames are interpreted.
        """
        self._preview_channels = channels

    def set_capture_fps(self, fps: float) -> None:
        """
        Set the sensor framerate (applies to both the preview and, later,
        the recording stream — they share the same sensor capture).
        Also affects auto-exposure: at low fps the sensor can use a longer
        exposure time, so the preview brightness reflects what recording
        at that framerate will actually look like.

        If the camera isn't running yet, the value is stored and applied
        automatically the next time start_preview() runs.
        """
        self._target_fps = fps
        if self._preview_running:
            try:
                self._camera.set_controls({"FrameRate": fps})
            except Exception:
                pass   # camera may be mid-reconfiguration; reapplied on restart

    # ── Preview ────────────────────────────────────────────────────────────────

    def start_preview(self, callback: Callable[[np.ndarray], None], fps: int = 10) -> None:
        """
        Start delivering preview frames to callback at up to fps frames/second.
        Frames are numpy arrays (RGB, uint8).

        picamera2 requires the lores stream to be YUV — it cannot be RGB.
        We capture YUV420 from lores and convert to RGB in the preview loop.
        """
        from constants import PREVIEW_WIDTH
        self._preview_callback = callback
        self._preview_fps      = fps
        self._preview_running  = True

        # Size the preview stream to the ACTIVE MODE's aspect ratio. A fixed
        # 16:9 preview against a 4:3 sensor mode would crop the frame, so the
        # height is derived from the mode rather than hardcoded. Both
        # dimensions are rounded to even numbers, which YUV420 requires.
        preview_width  = PREVIEW_WIDTH
        preview_height = int(
            preview_width * self._active_mode.height / self._active_mode.width
        )
        preview_width  -= preview_width  % 2
        preview_height -= preview_height % 2

        preview_config = self._camera.create_preview_configuration(
            main  = {"size":   (self._active_mode.width, self._active_mode.height),
                     "format": "RGB888"},
            lores = {"size":   (preview_width, preview_height),
                     "format": "YUV420"},   # lores must be YUV — converted below
        )
        self._camera.configure(preview_config)
        self._camera.start()

        # Apply the recording framerate to the sensor if one has been set —
        # this makes exposure/brightness in the preview match what recording
        # at that fps will actually produce.
        if self._target_fps is not None:
            try:
                self._camera.set_controls({"FrameRate": self._target_fps})
            except Exception:
                pass

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
                if self._preview_channels == 1:
                    # Greyscale: just the Y (luma) plane — no colour conversion,
                    # no risk of red/blue channel-order bugs, and cheaper per frame.
                    frame = self._yuv420_extract_y(yuv_frame)
                else:
                    frame = self._yuv420_to_rgb(yuv_frame)
                if self._preview_callback is not None:
                    self._preview_callback(frame)
            except Exception:
                pass
            elapsed   = time.perf_counter() - loop_start
            sleep_for = max(0.0, frame_interval - elapsed)
            time.sleep(sleep_for)

    @staticmethod
    def _yuv420_extract_y(yuv_frame: np.ndarray) -> np.ndarray:
        """
        Extract just the Y (luma) plane from a YUV420 (I420 planar) array.
        The Y plane occupies the first `height` rows of the packed array;
        U and V planes follow below it. Returns a 2D greyscale array —
        the preview widget already handles 2D frames by stacking them
        to RGB for display.
        """
        total_rows = yuv_frame.shape[0]
        height     = total_rows * 2 // 3     # I420 packs Y + U/4 + V/4 = 1.5×height rows
        return yuv_frame[:height, :]

    @staticmethod
    def _yuv420_to_rgb(yuv_frame: np.ndarray) -> np.ndarray:
        """
        Convert a YUV420 (I420 planar) numpy array, as returned by picamera2,
        directly to RGB uint8.
        Requires opencv: sudo apt install -y python3-opencv

        Note: if colours still look wrong (e.g. red/blue swapped or a
        cyan/magenta tint) after this, picamera2's plane order may not match
        OpenCV's I420 assumption. Try COLOR_YUV2RGB_YV12 instead, which
        swaps the U/V plane order.
        """
        import cv2
        return cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2RGB_I420)

    def stop_preview(self) -> None:
        self._preview_running = False
        if self._preview_thread:
            self._preview_thread.join(timeout=2.0)
            self._preview_thread = None
        try:
            self._camera.stop()
        except Exception:
            pass   # camera may not have been started yet

    # ── Capture ────────────────────────────────────────────────────────────────

    def pause_preview(self) -> None:
        """
        Stop the preview THREAD without stopping the camera.

        Essential before recording. picamera2's capture_array() consumes one
        request from the camera's queue per call, so a preview thread and a
        recording thread both calling it take alternate frames — the recording
        then runs at half the requested rate while its container header still
        claims the full rate, silently doubling every measured speed.

        During recording the record loop serves the preview itself, from the
        same request (see capture_frame).
        """
        self._preview_running = False
        if self._preview_thread:
            self._preview_thread.join(timeout=2.0)
            self._preview_thread = None

    def resume_preview(self) -> None:
        """Restart the preview thread after recording, if one was configured."""
        if self._preview_callback is not None and not self._preview_running:
            self._preview_running = True
            frame_interval = 1.0 / self._preview_fps
            self._preview_thread = threading.Thread(
                target=self._preview_loop, args=(frame_interval,), daemon=True
            )
            self._preview_thread.start()

    def capture_frame(self, channels: int = 3, want_preview: bool = False):
        """
        Capture one frame. Returns (recording_frame, preview_frame_or_None).

        Both arrays come from a SINGLE camera request, so asking for a preview
        frame costs no capture rate — unlike calling capture_array twice, which
        would consume two requests and halve the recording rate.

        recording_frame is 2D greyscale when channels == 1, else 3D RGB.
        preview_frame is always RGB for display.
        """
        request = self._camera.capture_request()
        try:
            main_frame    = request.make_array("main")
            preview_frame = request.make_array("lores") if want_preview else None
        finally:
            # Requests are pooled; failing to release one stalls the camera
            # after a few frames.
            request.release()

        # ── Recording frame ────────────────────────────────────────────────────
        if channels == 1:
            if main_frame.ndim == 3:
                import cv2
                recording_frame = cv2.cvtColor(main_frame, cv2.COLOR_RGB2GRAY)
            else:
                recording_frame = main_frame
        else:
            if main_frame.ndim == 2:
                recording_frame = np.stack([main_frame] * 3, axis=2)
            elif main_frame.shape[2] == 4:
                recording_frame = main_frame[:, :, :3]
            else:
                recording_frame = main_frame

        # ── Preview frame ──────────────────────────────────────────────────────
        display_frame = None
        if preview_frame is not None:
            display_frame = (
                self._yuv420_extract_y(preview_frame) if self._preview_channels == 1
                else self._yuv420_to_rgb(preview_frame)
            )

        return recording_frame, display_frame

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
        self.sensor_modes     = self._fake_sensor_modes()
        self.dropped_frames   = 0
        self._preview_running = False
        self._preview_thread: threading.Thread | None = None
        self._preview_channels = 3
        self._target_fps: float | None = None
        self._preview_callback = None
        self._preview_fps = 10

    def _fake_sensor_modes(self) -> list[SensorMode]:
        """
        Mirrors the real IMX477 mode list, including crop geometry, so the
        field-of-view logic can be exercised without hardware.
        """
        SENSOR_W, SENSOR_H = 4056, 3040
        modes = [
            # width height max_fps bits  crop_w crop_h
            SensorMode(0, 4056, 3040,  17.39, 8, 4056, 3040, SENSOR_W, SENSOR_H),
            SensorMode(1, 2028, 1520,  66.38, 8, 4056, 3040, SENSOR_W, SENSOR_H),
            SensorMode(2, 2028, 1080,  92.27, 8, 4056, 2160, SENSOR_W, SENSOR_H),
            SensorMode(3, 1332,  990, 147.91, 8, 2664, 1980, SENSOR_W, SENSOR_H),
        ]
        modes.sort(key=lambda m: (m.width * m.height, m.max_fps), reverse=True)
        return modes

    def set_mode(self, mode: SensorMode) -> None:
        pass

    def set_colour_mode(self, channels: int) -> None:
        self._preview_channels = channels

    def set_capture_fps(self, fps: float) -> None:
        self._target_fps = fps   # stored for interface parity; stub ignores it

    def start_preview(self, callback: Callable[[np.ndarray], None], fps: int = 10) -> None:
        from constants import PREVIEW_WIDTH
        self._preview_callback = callback
        self._preview_fps      = fps
        self._preview_running  = True
        frame_interval         = 1.0 / fps

        mode           = self.sensor_modes[0]
        preview_width  = PREVIEW_WIDTH
        preview_height = int(preview_width * mode.height / mode.width)

        def loop():
            while self._preview_running:
                start = time.perf_counter()
                if self._preview_channels == 1:
                    frame = np.random.randint(
                        60, 180, (preview_height, preview_width), dtype=np.uint8
                    )
                else:
                    frame = np.random.randint(
                        60, 180, (preview_height, preview_width, 3), dtype=np.uint8
                    )
                callback(frame)
                elapsed = time.perf_counter() - start
                time.sleep(max(0.0, frame_interval - elapsed))

        self._preview_thread = threading.Thread(target=loop, daemon=True)
        self._preview_thread.start()

    def stop_preview(self) -> None:
        self._preview_running = False
        if self._preview_thread:
            self._preview_thread.join(timeout=2.0)

    def pause_preview(self) -> None:
        self._preview_running = False
        if self._preview_thread:
            self._preview_thread.join(timeout=2.0)
            self._preview_thread = None

    def resume_preview(self) -> None:
        if self._preview_callback is not None and not self._preview_running:
            self.start_preview(self._preview_callback, self._preview_fps)

    def capture_frame(self, channels: int = 3, want_preview: bool = False):
        """Synthetic frame pair, mirroring the real camera's interface."""
        height, width = 480, 640
        if channels == 1:
            recording_frame = np.random.randint(60, 180, (height, width), dtype=np.uint8)
        else:
            recording_frame = np.random.randint(60, 180, (height, width, 3), dtype=np.uint8)
        display_frame = recording_frame if want_preview else None
        return recording_frame, display_frame

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
