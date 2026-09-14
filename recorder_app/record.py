"""
record.py
=========
Recording engine for the RPi Recorder.

Architecture
------------
Two threads run during a recording:

  Capture thread  — grabs frames from the sensor at the target framerate and
                    pushes them onto a bounded queue. If the queue is full,
                    the frame is counted as DROPPED and discarded. This is the
                    honest signal that the storage device cannot keep up.

  Writer thread   — pulls frames off the queue and writes them to disk.
                    Slow disk I/O backs up here rather than stalling the sensor.

Separating these means a momentary SD card stall costs queued frames rather
than corrupting capture timing, and gives us an exact dropped-frame count.

Output layout (no dates in filenames — dates live in the metadata):
  Video:       {save_dir}/{file_name}.avi
               {save_dir}/{file_name}_metadata.yaml
  Image stack: {save_dir}/{file_name}/{file_name}_00001.tiff
               {save_dir}/{file_name}/metadata.yaml
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from constants import OUTPUT_FORMATS, APP_VERSION


# =============================================================================
# Configuration for one recording session
# =============================================================================

@dataclass
class RecordingSettings:
    """Everything needed to start a recording. Assembled from the UI form."""
    save_dir:       Path
    file_name:      str
    folder_name:    str
    format_label:   str
    frame_width:    int
    frame_height:   int
    fps:            float
    channels:       int              # 1 = greyscale, 3 = colour
    duration_s:     float | None     # None = record until stopped
    fov_fraction:   float = 1.0      # fraction of full sensor width this mode sees
    metadata:       dict = field(default_factory=dict)

    # ── Derived paths ──────────────────────────────────────────────────────────

    @property
    def is_image_stack(self) -> bool:
        return "stack" in self.format_label.lower()

    @property
    def file_extension(self) -> str:
        for display_label, extension, _description in OUTPUT_FORMATS:
            if display_label == self.format_label:
                return extension
        return ".avi"

    @property
    def output_dir(self) -> Path:
        """Directory that will hold the output (created if needed)."""
        if self.is_image_stack:
            return self.save_dir / self.file_name
        return self.save_dir

    @property
    def video_file(self) -> Path:
        return self.save_dir / f"{self.file_name}{self.file_extension}"

    @property
    def metadata_file(self) -> Path:
        if self.is_image_stack:
            return self.output_dir / "metadata.yaml"
        return self.save_dir / f"{self.file_name}_metadata.yaml"


# =============================================================================
# Statistics reported live during recording
# =============================================================================

@dataclass
class RecordingStats:
    frames_captured: int   = 0
    frames_written:  int   = 0
    frames_dropped:  int   = 0    # queue was full: the DISK could not keep up
    frames_missed:   int   = 0    # schedule slipped: the CAMERA could not keep up
    elapsed_s:       float = 0.0
    queue_depth:     int   = 0

    @property
    def drop_rate_pct(self) -> float:
        total = self.frames_captured + self.frames_dropped
        if total == 0:
            return 0.0
        return round(100.0 * self.frames_dropped / total, 1)

    @property
    def miss_rate_pct(self) -> float:
        """
        Share of scheduled frames that were never captured.

        Distinct from drop rate: a dropped frame was captured but could not be
        written, whereas a missed frame never existed. Both leave gaps in the
        recording, but they have different causes and different fixes.
        """
        expected = self.frames_captured + self.frames_missed
        if expected == 0:
            return 0.0
        return round(100.0 * self.frames_missed / expected, 1)


# =============================================================================
# Frame writers — one per output format
# =============================================================================

class VideoWriter:
    """
    Writes frames into a single video file using OpenCV's VideoWriter.

    MJPEG is written with the MJPG fourcc; H.264 with mp4v (OpenCV's H.264
    support via avc1 is not reliably available on Raspberry Pi OS builds,
    and mp4v produces a comparable inter-frame-compressed MP4).
    """

    _FOURCC_BY_FORMAT = {
        "MJPEG video (.avi)": "MJPG",
        "H.264 video (.mp4)": "mp4v",
    }

    def __init__(self, settings: RecordingSettings):
        import cv2
        self._cv2 = cv2

        fourcc_code = self._FOURCC_BY_FORMAT.get(settings.format_label, "MJPG")
        fourcc      = cv2.VideoWriter_fourcc(*fourcc_code)
        is_colour   = settings.channels == 3

        settings.output_dir.mkdir(parents=True, exist_ok=True)
        self._writer = cv2.VideoWriter(
            str(settings.video_file),
            fourcc,
            settings.fps,
            (settings.frame_width, settings.frame_height),
            is_colour,
        )
        if not self._writer.isOpened():
            raise RuntimeError(
                f"Could not open video writer for {settings.video_file}. "
                f"Check that the codec '{fourcc_code}' is available."
            )
        self._is_colour = is_colour

    def write(self, frame: np.ndarray, frame_index: int) -> None:
        # OpenCV expects BGR for colour frames; our pipeline produces RGB
        if self._is_colour and frame.ndim == 3:
            frame = self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2BGR)
        self._writer.write(frame)

    def close(self) -> None:
        self._writer.release()


class ImageStackWriter:
    """
    Writes each frame as a separate image file in a dedicated folder.
    Files are named {file_name}_00001.{ext}, incrementing with a 5-digit counter.
    """

    def __init__(self, settings: RecordingSettings):
        import cv2
        self._cv2       = cv2
        self._settings  = settings
        self._extension = settings.file_extension
        settings.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, frame: np.ndarray, frame_index: int) -> None:
        # Frame counter is 1-based and zero-padded to 5 digits
        image_file = (
            self._settings.output_dir
            / f"{self._settings.file_name}_{frame_index + 1:05d}{self._extension}"
        )
        # OpenCV expects BGR for colour; greyscale 2D arrays pass through as-is
        if frame.ndim == 3:
            frame = self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2BGR)
        self._cv2.imwrite(str(image_file), frame)

    def close(self) -> None:
        pass   # nothing to finalise for an image stack


def make_writer(settings: RecordingSettings):
    """Return the appropriate writer for the selected output format."""
    if settings.is_image_stack:
        return ImageStackWriter(settings)
    return VideoWriter(settings)


# =============================================================================
# Recording session — manages capture and writer threads
# =============================================================================

class RecordingSession:
    """
    Runs one recording from start to finish.

    Usage:
        session = RecordingSession(camera, settings, queue_size=60)
        session.start()
        ...  # poll session.stats for live UI updates
        summary = session.stop()
    """

    def __init__(self, camera, settings: RecordingSettings, queue_size: int = 60,
                 preview_callback=None, preview_fps: float = 10.0):
        self._camera    = camera
        self._settings  = settings
        # The record loop serves the preview from the same camera request it
        # uses for recording, so the preview costs no capture rate.
        self._preview_callback = preview_callback
        self._preview_fps      = preview_fps
        self._frame_times: list[float] = []
        # Accumulated schedule slippage, used to count missed frames when each
        # frame runs slightly over budget rather than whole slots being skipped
        self._slippage_s = 0.0
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._writer    = None

        self.stats      = RecordingStats()
        self._running   = False
        self._start_time: float | None = None
        self._stop_time:  float | None = None
        self._start_datetime: datetime | None = None

        self._capture_thread: threading.Thread | None = None
        self._writer_thread:  threading.Thread | None = None
        self._error: Exception | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the writer and launch both threads."""
        self._writer         = make_writer(self._settings)
        self._running        = True
        self._start_time     = time.perf_counter()
        self._start_datetime = datetime.now()

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._writer_thread  = threading.Thread(target=self._writer_loop,  daemon=True)
        self._capture_thread.start()
        self._writer_thread.start()

    def request_stop(self) -> None:
        """
        Ask the recording to stop, WITHOUT blocking.

        The capture thread notices the flag within one frame interval, stops,
        and puts the sentinel onto the queue. The writer then drains whatever
        is still queued and exits on its own.

        Split from finalize() so the UI does not freeze while a large buffer is
        written out — it can keep polling frames_remaining and show progress.
        """
        self._running = False

    @property
    def is_finished(self) -> bool:
        """True once the writer thread has drained the queue and exited."""
        if self._writer_thread is None:
            return True
        return not self._writer_thread.is_alive()

    @property
    def frames_remaining(self) -> int:
        """Frames still buffered and waiting to be written."""
        return self._queue.qsize()

    def finalize(self) -> dict:
        """
        Close the writer and return the summary. Call only once is_finished is
        True, otherwise this blocks until the threads end.
        """
        if self._capture_thread:
            self._capture_thread.join(timeout=5.0)
        if self._writer_thread:
            self._writer_thread.join(timeout=60.0)

        if self._writer:
            self._writer.close()

        actual_duration_s = (
            self._stop_time - self._start_time
            if self._stop_time and self._start_time else 0.0
        )

        effective_fps = (
            round(self.stats.frames_written / actual_duration_s, 2)
            if actual_duration_s > 0 else 0.0
        )

        # Write the per-frame timestamps. The container header stores only a
        # nominal frame rate, so these are the authoritative timing record for
        # any analysis that measures speed or duration.
        timestamps_file = self._write_frame_times()

        return {
            "start_datetime":     self._start_datetime.isoformat() if self._start_datetime else None,
            "actual_duration_s":  round(actual_duration_s, 2),
            "requested_fps":      self._settings.fps,
            "effective_fps":      effective_fps,
            "fps_shortfall_pct":  round(
                                      100.0 * (self._settings.fps - effective_fps)
                                      / self._settings.fps, 1
                                  ) if self._settings.fps > 0 else 0.0,
            "frames_written":     self.stats.frames_written,
            "frames_dropped":     self.stats.frames_dropped,
            "frames_missed":      self.stats.frames_missed,
            "drop_rate_pct":      self.stats.drop_rate_pct,
            "miss_rate_pct":      self.stats.miss_rate_pct,
            "frame_times_file":   str(timestamps_file) if timestamps_file else None,
            "error":              str(self._error) if self._error else None,
        }

    def _write_frame_times(self):
        """
        Write frame index and capture time to a CSV beside the footage.

        Kept separate from the metadata YAML because it is one row per frame —
        potentially tens of thousands — and belongs in a format built for that.
        """
        if not self._frame_times:
            return None

        if self._settings.is_image_stack:
            timestamps_file = self._settings.output_dir / "frame_times.csv"
        else:
            timestamps_file = (
                self._settings.save_dir / f"{self._settings.file_name}_frame_times.csv"
            )

        try:
            timestamps_file.parent.mkdir(parents=True, exist_ok=True)
            with timestamps_file.open("w", newline="") as file_handle:
                file_handle.write("frame_index,time_s\n")
                for frame_index, capture_time in enumerate(self._frame_times, start=1):
                    file_handle.write(f"{frame_index},{capture_time:.6f}\n")
            return timestamps_file
        except OSError:
            return None

    def stop(self) -> dict:
        """
        Blocking stop: request, wait, finalize. Convenient for scripts and
        tests; the UI uses request_stop() plus finalize() so it can stay
        responsive while the buffer drains.
        """
        self.request_stop()
        while not self.is_finished:
            time.sleep(0.05)
        return self.finalize()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def error(self) -> Exception | None:
        return self._error

    # ── Capture thread ─────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """
        Grab frames at the target interval and push them onto the queue.

        Two distinct failure modes are tracked separately:

          frames_dropped — the queue was full, so a captured frame was thrown
                           away. The DISK is too slow.
          frames_missed  — the loop fell behind schedule, so a frame was never
                           captured at all. The CAMERA or the per-frame work is
                           too slow for the requested rate.

        Conflating them hides real problems: a recording can run at half the
        requested rate with zero drops, producing a file whose header claims a
        frame rate it never achieved.
        """
        frame_interval   = 1.0 / self._settings.fps
        preview_interval = 1.0 / self._preview_fps if self._preview_callback else None
        next_frame_at    = time.perf_counter()
        next_preview_at  = time.perf_counter()

        while self._running:
            # Stop automatically once the requested duration has elapsed
            if self._settings.duration_s is not None and self._start_time is not None:
                if time.perf_counter() - self._start_time >= self._settings.duration_s:
                    self._running = False
                    break

            now          = time.perf_counter()
            want_preview = (
                preview_interval is not None and now >= next_preview_at
            )

            try:
                frame, preview_frame = self._camera.capture_frame(
                    self._settings.channels, want_preview
                )
            except Exception as capture_error:
                self._error   = capture_error
                self._running = False
                break

            capture_time = time.perf_counter()

            if want_preview:
                next_preview_at = capture_time + preview_interval
                if preview_frame is not None and self._preview_callback is not None:
                    try:
                        self._preview_callback(preview_frame)
                    except Exception:
                        pass    # a preview failure must never stop a recording

            try:
                self._queue.put_nowait(frame)
                self.stats.frames_captured += 1
                # Timestamps are the authoritative timing record: the container
                # header only stores a nominal rate, which is wrong whenever the
                # loop could not keep up.
                self._frame_times.append(capture_time - (self._start_time or capture_time))
            except queue.Full:
                self.stats.frames_dropped += 1

            self.stats.queue_depth = self._queue.qsize()
            self.stats.elapsed_s   = capture_time - (self._start_time or 0.0)

            # Sleep until the next scheduled frame, correcting for the time the
            # capture itself took
            next_frame_at += frame_interval
            sleep_for = next_frame_at - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                # Behind schedule. Accumulate the slippage rather than counting
                # only whole missed slots: when every frame runs slightly over
                # its budget, no single slot is ever fully skipped, yet the rate
                # still falls short. Counting whole slots alone would report
                # zero missed frames on a recording running 20% slow.
                self._slippage_s += -sleep_for
                while self._slippage_s >= frame_interval:
                    self.stats.frames_missed += 1
                    self._slippage_s -= frame_interval
                next_frame_at = time.perf_counter()

        # Capture has ended. Record when, so the reported duration covers the
        # recording rather than also counting the time spent draining the
        # buffer afterwards.
        self._stop_time = time.perf_counter()

        # The sentinel is emitted HERE rather than by the caller, so it can
        # never be queued while this thread is still adding frames — which
        # would make the writer stop early and silently lose the tail.
        self._queue.put(None)

    # ── Writer thread ──────────────────────────────────────────────────────────

    def _writer_loop(self) -> None:
        """Pull frames off the queue and write them until sentinel is received."""
        while True:
            frame = self._queue.get()
            if frame is None:      # sentinel: capture finished and queue drained
                break
            try:
                self._writer.write(frame, self.stats.frames_written)
                self.stats.frames_written += 1
            except Exception as write_error:
                self._error   = write_error
                self._running = False
                break
