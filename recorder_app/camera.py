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
    from picamera2 import Picamera2, MappedArray
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
        self._recording_channels: int | None = None   # main stream's current format
        self._camera_started = False
        # Rotating frame buffers, keyed by shape — see _get_frame_buffer
        self._frame_buffers: dict = {}
        self._frame_buffer_index: dict = {}
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
        # The main stream's resolution is part of what prepare_for_recording()
        # configures, so a mode change invalidates it regardless of whether a
        # preview is running — otherwise a stale _recording_channels could
        # skip reconfiguration and the next recording would capture at the
        # OLD mode's resolution.
        self._recording_channels = None
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
        # Apply whenever the camera is running, not only while the preview is.
        # The preview is paused during recording and measurement, and gating
        # on it meant a new rate set then was silently ignored — so a
        # measurement asking for the sensor maximum still ran at the UI's rate.
        if self._camera_started:
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
        self._camera_started = True
        # start_preview always configures main as RGB888 (colour), so the
        # next capture_frame(channels=1, ...) must not assume a YUV420 main
        # stream is already in place — prepare_for_recording() will fix this.
        self._recording_channels = 3

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
        Return the Y (luma) plane of a YUV420 (I420 planar) array as a view.

        The Y plane occupies the first two thirds of the rows; U and V follow
        below it. Used for the preview only — the recording path crops to the
        configured size as well, since rows may carry alignment padding.
        """
        height = yuv_frame.shape[0] * 2 // 3    # I420 packs Y + U/4 + V/4 = 1.5×height rows
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
        self._camera_started      = False
        self._recording_channels  = None
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

    def prepare_for_recording(self, channels: int) -> None:
        """
        Reconfigure the main stream to match what recording actually needs,
        BEFORE capture starts.

        Without this, a greyscale recording still pulls a full 3-channel RGB
        frame through the camera's colour pipeline (demosaic, colour
        correction, gamma) on every frame — a substantial ISP and memory-
        bandwidth cost — and only discards the colour afterward in software.
        That cost dwarfs the JPEG-encoding saving greyscale is meant to give,
        which is why greyscale mode measured little faster than colour despite
        encoding a third of the data: the expensive part was never skipped.

        Requesting the main stream as YUV420 for a greyscale recording and
        taking only the Y plane (the same trick already used for the lores
        preview stream) skips that colour pipeline entirely. Call this once,
        immediately before a recording starts; call it again before the next
        one, since it may need switching back.

        Always leaves the preview thread STOPPED, regardless of whether it was
        running beforehand — resuming it is the caller's responsibility, done
        only once recording has fully finished. Auto-resuming here would let
        the preview thread and the recording both consume camera requests at
        once, exactly the contention that halved the frame rate before this
        was fixed (see pause_preview).
        """
        if channels == self._recording_channels and self._camera_started:
            self._warm_frame_pool(channels)
            return   # already configured correctly; avoid an unneeded restart

        self.pause_preview()
        try:
            self._camera.stop()
        except Exception:
            pass

        main_format = "YUV420" if channels == 1 else "RGB888"
        recording_config = self._camera.create_video_configuration(
            main  = {"size": (self._active_mode.width, self._active_mode.height),
                     "format": main_format},
            lores = {"size": self._preview_stream_size(),
                     "format": "YUV420"},
        )
        self._camera.configure(recording_config)
        self._camera.start()
        self._camera_started      = True
        self._recording_channels  = channels

        if self._target_fps is not None:
            try:
                self._camera.set_controls({"FrameRate": self._target_fps})
            except Exception:
                pass

        self._warm_frame_pool(channels)

    def _warm_frame_pool(self, channels: int) -> None:
        """
        Allocate the frame pool for this recording before capture starts, and
        free pools for any other frame size. A recording uses one size only,
        and on a 2 GB Pi a single 4K pool is already ~250 MB.
        """
        width, height = self._active_mode.width, self._active_mode.height
        shape = (height, width) if channels == 1 else (height, width, 3)
        wanted_key = (shape, np.dtype(np.uint8).str)
        for key in [key for key in self._frame_buffers if key != wanted_key]:
            del self._frame_buffers[key]
            self._frame_buffer_index.pop(key, None)
        self._get_frame_buffer(shape, np.uint8)

    def _preview_stream_size(self) -> tuple[int, int]:
        from constants import PREVIEW_WIDTH
        preview_width  = PREVIEW_WIDTH
        preview_height = int(
            preview_width * self._active_mode.height / self._active_mode.width
        )
        preview_width  -= preview_width  % 2
        preview_height -= preview_height % 2
        return (preview_width, preview_height)

    # Pooled buffers must OUTNUMBER constants.FRAME_QUEUE_SIZE: a frame handed
    # out here can sit in the recording queue until the writer reaches it, so
    # the pool has to outlast the deepest the queue can get, or a buffer would
    # be overwritten while a queued frame still references it.
    #
    # Capped by total bytes rather than a fixed count, because a 4K colour
    # frame is 37 MB — a count that is reasonable for greyscale would reserve
    # most of the Pi's RAM for colour. Above the cap, pooling is skipped and
    # frames are allocated per frame: slower, but correct, and only
    # reached at resolutions where allocation is a small share of the cost.
    _BUFFER_POOL_MAX_BYTES = 320 * 1024 * 1024

    def _get_frame_buffer(self, shape, dtype):
        """
        Return a reusable buffer of the given shape from a rotating pool.

        At 4K a frame is ~12 MB, so allocating a fresh array per frame costs
        real time on the Pi — page faults and zeroing, not just the copy. The
        measured crop/copy cost there was over ten times the same operation on
        a desktop, because the camera's DMA buffer lives in uncached memory
        and every byte is read slowly.

        Buffers ROTATE rather than being one reused array: frames are handed
        to writer threads asynchronously, so a buffer handed out now may still
        be being encoded several frames later. The pool is larger than the
        number of frames that can be in flight, so a buffer is never
        overwritten while a writer still holds it.
        """
        from constants import FRAME_QUEUE_SIZE

        key = (shape, np.dtype(dtype).str)
        pool = self._frame_buffers.get(key)

        if pool is None:
            frame_bytes = int(np.prod(shape)) * np.dtype(dtype).itemsize
            # The queue can be FULL while further frames are being captured,
            # encoded, or held briefly by a writer, so the pool needs real
            # margin over the queue depth — not just one or two spare buffers.
            # Sizing it at twice the queue plus a margin was verified against a
            # test that holds a full queue of frames and keeps capturing; with
            # a tighter pool that test corrupts most of the held frames.
            wanted = FRAME_QUEUE_SIZE * 2 + 4
            if frame_bytes * wanted > self._BUFFER_POOL_MAX_BYTES:
                # Too large to pool safely; fall back to per-frame allocation
                self._frame_buffers[key] = []
                return None
            # np.full writes every byte, so the pages are mapped now. With
            # np.empty they would fault in on first use, slowing the first
            # couple of dozen frames of a recording noticeably.
            pool = [np.full(shape, 0, dtype=dtype) for _ in range(wanted)]
            self._frame_buffers[key] = pool
            self._frame_buffer_index[key] = 0

        if not pool:
            return None     # pooling disabled for this frame size

        index = self._frame_buffer_index[key]
        self._frame_buffer_index[key] = (index + 1) % len(pool)
        return pool[index]


    def capture_frame(self, channels: int = 3, want_preview: bool = False,
                      timings: dict | None = None, discard: bool = False):
        """
        Capture one frame. Returns (recording_frame, preview_frame_or_None).

        Both arrays come from a SINGLE camera request, so asking for a preview
        frame costs no capture rate — unlike calling capture_array twice, which
        would consume two requests and halve the recording rate.

        With `discard`, the request is still consumed (keeping the camera's
        pace and the preview) but the recording frame is not copied and None
        is returned in its place. The record loop uses this when its queue is
        full, so a frame that would be dropped costs no copy.

        Call prepare_for_recording(channels) before the first call in a
        recording — this method assumes the main stream is already configured
        to match, and does not reconfigure it itself, since that involves a
        camera restart that must not happen mid-recording.

        If `timings` is given, per-stage durations in milliseconds are written
        into it: wait_ms (for the camera to deliver), copy_ms (out of the
        camera buffer) and preview_ms (preview conversion).

        recording_frame is 2D greyscale when channels == 1, else 3D BGR —
        picamera2's "RGB888" is B,G,R in memory, which is the order OpenCV
        and ffmpeg's bgr24 expect, so writers use it without conversion.
        preview_frame is always RGB (or greyscale) for display.
        """
        request_start = time.perf_counter()
        request = self._camera.capture_request()
        request_end = time.perf_counter()

        try:
            recording_frame = None
            if not discard:
                # MappedArray exposes the camera's DMA buffer without copying.
                # That memory is uncached and slow to read, so exactly one
                # copy is made, of only the pixels kept (no chroma planes, no
                # row padding), straight into a pooled buffer.
                with MappedArray(request, "main", write=False) as mapped:
                    recording_frame = self._copy_recording_frame(mapped.array, channels)
            copy_end = time.perf_counter()
            preview_frame = request.make_array("lores") if want_preview else None
        finally:
            # Requests are pooled; failing to release one stalls the camera
            # after a few frames.
            request.release()

        display_frame = None
        if preview_frame is not None:
            display_frame = (
                self._yuv420_extract_y(preview_frame) if self._preview_channels == 1
                else self._yuv420_to_rgb(preview_frame)
            )

        if timings is not None:
            timings["wait_ms"]    = (request_end - request_start) * 1000
            timings["copy_ms"]    = (copy_end - request_end) * 1000
            timings["preview_ms"] = (time.perf_counter() - copy_end) * 1000

        return recording_frame, display_frame

    def _copy_recording_frame(self, source: np.ndarray, channels: int) -> np.ndarray:
        """
        Copy the recording frame out of a mapped camera buffer.

        `source` is the main stream as picamera2 maps it: for YUV420 a 2D
        array of 1.5×height rows by the padded stride, for RGB888 a 3D
        (height, width, 3) view that may skip row padding. Cropping to the
        configured size matters: cv2.VideoWriter silently discards frames
        whose size differs from what it was opened with, leaving a file with
        a header and no frames.
        """
        width, height = self._active_mode.width, self._active_mode.height

        if source.ndim == 2:
            luma = source[:height, :width]
            if channels == 1:
                return self._copy_into_pool(luma)
            # Colour requested but the stream is YUV420 (prepare_for_recording
            # was not called): deliver the luma as three equal channels.
            return np.stack([luma] * 3, axis=2)

        pixels = source[:height, :width, :3]
        if channels == 1:
            return self._bgr_to_grey_fallback(np.ascontiguousarray(pixels))
        return self._copy_into_pool(pixels)

    def _copy_into_pool(self, view: np.ndarray) -> np.ndarray:
        buffer = self._get_frame_buffer(view.shape, view.dtype)
        if buffer is None:              # pooling disabled for this frame size
            return np.array(view)
        np.copyto(buffer, view)
        return buffer

    @staticmethod
    def _bgr_to_grey_fallback(bgr_frame: np.ndarray) -> np.ndarray:
        """
        Convert a BGR frame to greyscale. Only used if capture_frame is
        called with channels == 1 before prepare_for_recording() has run —
        correct, but pays the full-colour capture cost this method exists to
        avoid. A sign prepare_for_recording() was skipped somewhere.
        """
        import cv2
        return cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)

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
        self._active_mode     = self.sensor_modes[0]
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
        self._active_mode = mode

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

    def prepare_for_recording(self, channels: int) -> None:
        """No real stream to reconfigure — pause preview for interface parity."""
        self.pause_preview()

    def capture_frame(self, channels: int = 3, want_preview: bool = False,
                      timings: dict | None = None, discard: bool = False):
        """
        Synthetic frame pair, mirroring the real camera's interface.

        Sized from the ACTIVE SENSOR MODE rather than a fixed resolution, so
        frames match what the writer was opened for. A fixed size here would
        trip the writer's dimension guard on every recording.
        """
        width  = self._active_mode.width
        height = self._active_mode.height
        if channels == 1:
            recording_frame = np.random.randint(60, 180, (height, width), dtype=np.uint8)
        else:
            recording_frame = np.random.randint(60, 180, (height, width, 3), dtype=np.uint8)
        display_frame = recording_frame if want_preview else None
        if timings is not None:
            timings["wait_ms"] = timings["copy_ms"] = timings["preview_ms"] = 0.0
        return (None if discard else recording_frame), display_frame

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
