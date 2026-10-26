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
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

import formats
from formats import OutputFormat

from constants import (APP_VERSION,
                       PNG_COMPRESSION_LEVEL, PNG_MODE, TIFF_COMPRESSION,
                       IMAGE_STACK_WORKERS,
                       FRAME_QUEUE_SIZE, ENABLE_HARDWARE_H264)


# =============================================================================
# Configuration for one recording session
# =============================================================================

@dataclass
class RecordingSettings:
    """Everything needed to start a recording. Assembled from the UI form."""
    save_dir:       Path
    file_name:      str
    output_format:  OutputFormat
    frame_width:    int
    frame_height:   int
    fps:            float
    channels:       int              # 1 = grayscale, 3 = color
    duration_s:     float | None     # None = record until stopped
    fov_fraction:   float = 1.0      # fraction of full sensor width this mode sees
    metadata:       dict = field(default_factory=dict)

    # ── Derived paths ──────────────────────────────────────────────────────────

    @property
    def is_image_stack(self) -> bool:
        return self.output_format.is_image_stack

    @property
    def file_extension(self) -> str:
        return self.output_format.extension

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
        formats.MJPEG.key: "MJPG",
        formats.H264.key:  "mp4v",
    }

    def __init__(self, settings: RecordingSettings):
        import cv2
        self._cv2 = cv2

        fourcc_code = self._FOURCC_BY_FORMAT.get(settings.output_format.key, "MJPG")
        fourcc      = cv2.VideoWriter_fourcc(*fourcc_code)
        is_color   = settings.channels == 3

        settings.output_dir.mkdir(parents=True, exist_ok=True)
        self._writer = cv2.VideoWriter(
            str(settings.video_file),
            fourcc,
            settings.fps,
            (settings.frame_width, settings.frame_height),
            is_color,
        )
        if not self._writer.isOpened():
            raise RuntimeError(
                f"Could not open video writer for {settings.video_file}. "
                f"Check that the codec '{fourcc_code}' is available."
            )
        self._is_color     = is_color
        self._expected_size = (settings.frame_width, settings.frame_height)

    def write(self, frame: np.ndarray, frame_index: int) -> None:
        # Verify the first frame matches what the writer was opened with.
        # cv2.VideoWriter.write() returns nothing and silently ignores frames
        # of the wrong size, so without this check a dimension mismatch
        # produces a valid-looking file containing only a header — which is
        # exactly what stride padding on the camera's YUV output once caused.
        if frame_index == 0:
            actual_height, actual_width = frame.shape[:2]
            if (actual_width, actual_height) != self._expected_size:
                raise ValueError(
                    f"Frame size {actual_width}x{actual_height} does not match "
                    f"the video's {self._expected_size[0]}x{self._expected_size[1]}. "
                    f"Every frame would be silently discarded, leaving an empty "
                    f"video file."
                )
            actual_channels = 1 if frame.ndim == 2 else frame.shape[2]
            expected_channels = 3 if self._is_color else 1
            if actual_channels != expected_channels:
                raise ValueError(
                    f"Frame has {actual_channels} channel(s) but the video was "
                    f"opened for {expected_channels}."
                )

        # Color frames are already BGR (picamera2's RGB888), as OpenCV expects
        self._writer.write(frame)

    def close(self) -> None:
        self._writer.release()


def image_encode_flags(cv2, extension: str) -> list:
    """
    OpenCV imwrite flags for one image format, from constants.py.

    One function for every image writer so the serial fallback and the
    parallel writer can never disagree about how a file is encoded.

    Each option is looked up with getattr because the Pi's OpenCV is whatever
    apt provides and may predate a flag. A missing flag means "use OpenCV's
    default", never an error: encoding slower than intended is better than a
    recording that will not start.
    """
    if extension == ".png":
        if PNG_COMPRESSION_LEVEL is not None:
            return [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION_LEVEL]
        if PNG_MODE == "store":
            png_filter = getattr(cv2, "IMWRITE_PNG_FILTER", None)
            filter_none = getattr(cv2, "IMWRITE_PNG_FILTER_NONE", None)
            if png_filter is not None and filter_none is not None:
                return [cv2.IMWRITE_PNG_COMPRESSION, 0, png_filter, filter_none]
            # Level 0 alone measured no faster than the default, so without
            # the filter flag there is nothing to gain; keep the default.
        return []

    if extension in (".tiff", ".tif"):
        tiff_flag = getattr(cv2, "IMWRITE_TIFF_COMPRESSION", None)
        if tiff_flag is None:
            return []
        codes = {"none": 1, "lzw": 5, "deflate": 8}   # TIFF compression tags
        if TIFF_COMPRESSION in codes:
            return [tiff_flag, codes[TIFF_COMPRESSION]]
    return []


# =============================================================================
# FFmpeg-based video writer — multithreaded MJPEG and hardware H.264
# =============================================================================

def _ffmpeg_encoder_available(encoder_name: str) -> bool:
    """Check whether this machine's ffmpeg build offers a given encoder."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        return encoder_name in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


_HARDWARE_H264_CACHE: dict = {}

# The Pi 4's hardware H.264 encoder cannot exceed 1920x1080. Above that it
# fails with "Could not find a valid device" — the same message it gives when
# no encoder device exists at all, which makes the real cause easy to
# misdiagnose. Checked before probing so the common case needs no subprocess.
HARDWARE_H264_MAX_WIDTH  = 1920
HARDWARE_H264_MAX_HEIGHT = 1088     # 1080 rounded up to the macroblock boundary


def hardware_h264_available(width: int, height: int, channels: int = 1) -> bool:
    """
    True when the Pi's hardware H.264 encoder can handle THIS exact pipeline.

    The probe runs the real recording command — same raw pixel format, same
    resolution, same encoder flags — with a few synthetic frames piped in, and
    checks the resulting file is valid.

    Testing anything less has failed twice. A probe using ffmpeg's synthetic
    `lavfi` source feeds the encoder yuv420p directly, skipping the pixel
    format conversion a real grayscale recording needs, and passed on a
    configuration that then died mid-recording with "VIDIOC_STREAMON failed".
    An earlier probe at a small fixed size passed on hardware that could not
    handle the actual resolution. Only an end-to-end probe predicts the
    end-to-end result.

    Cached per (resolution, channels); the answer cannot change while running.
    """
    cache_key = (width, height, channels)
    if cache_key in _HARDWARE_H264_CACHE:
        return _HARDWARE_H264_CACHE[cache_key]

    available = False
    if (ENABLE_HARDWARE_H264
            and width <= HARDWARE_H264_MAX_WIDTH
            and height <= HARDWARE_H264_MAX_HEIGHT
            and _ffmpeg_encoder_available("h264_v4l2m2m")):
        available = _probe_hardware_encode(width, height, channels)

    _HARDWARE_H264_CACHE[cache_key] = available
    return available


def _probe_hardware_encode(width: int, height: int, channels: int) -> bool:
    """
    Stream frames through the hardware encoder exactly as a recording does,
    and verify real output comes out.

    Streaming matters and is not a detail. Writing every frame at once and
    closing the pipe (subprocess.run with `input=`) takes a different path
    through the V4L2 encoder than feeding frames one at a time into a live
    pipe — the one-shot form passed on a configuration whose streaming form
    then died with "VIDIOC_STREAMON failed on output context". The probe
    therefore uses Popen, incremental writes and a real pause between frames,
    so it fails wherever a recording would.
    """
    import subprocess
    import tempfile

    pixel_format    = "gray" if channels == 1 else "bgr24"
    bytes_per_frame = width * height * (1 if channels == 1 else 3)
    probe_frames    = 8
    frame_payload   = b"\x10" * bytes_per_frame

    with tempfile.TemporaryDirectory() as temporary_dir:
        output_file = Path(temporary_dir) / "probe.mp4"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo",
            "-pix_fmt", pixel_format,
            "-s", f"{width}x{height}",
            "-r", "30",
            "-i", "-",
        ] + _HARDWARE_H264_ARGUMENTS + [str(output_file)]

        process = None
        try:
            process = subprocess.Popen(
                command,
                stdin  = subprocess.PIPE,
                stdout = subprocess.DEVNULL,
                stderr = subprocess.PIPE,
            )
            for _ in range(probe_frames):
                if process.poll() is not None:
                    return False                 # encoder already died
                process.stdin.write(frame_payload)
                process.stdin.flush()
                time.sleep(0.02)                 # let the encoder actually run
            process.stdin.close()
            process.wait(timeout=30)
        except (OSError, subprocess.SubprocessError, BrokenPipeError):
            if process is not None:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass
            return False

        # A zero exit code alone is not enough — ffmpeg can exit cleanly having
        # written nothing. Require a file with real content.
        return (process.returncode == 0
                and output_file.exists()
                and output_file.stat().st_size > 1000)


def disable_hardware_h264(width: int, height: int, channels: int) -> None:
    """
    Record that hardware encoding failed for this configuration, so later
    recordings in this session fall back to software instead of failing the
    same way again.

    Called when a recording dies despite the probe passing — no probe can
    anticipate everything, for instance the encoder device being held by
    another process at the moment recording starts.
    """
    _HARDWARE_H264_CACHE[(width, height, channels)] = False


# Encoder flags shared by the probe and the real recording, so the probe
# cannot drift out of sync with what actually runs.
_HARDWARE_H264_ARGUMENTS = [
    "-c:v", "h264_v4l2m2m",
    # Convert to yuv420p explicitly rather than leaving ffmpeg to negotiate it.
    # The V4L2 encoder is particular about its input format, and an implicit
    # conversion is what produced "VIDIOC_STREAMON failed" on grayscale input.
    "-vf", "format=yuv420p",
    # Hardware encoders take a bitrate rather than a quality scale. Generous,
    # since the point here is speed, not small files.
    "-b:v", "25M",
]

_SOFTWARE_H264_ARGUMENTS = [
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-crf", "20",
    "-threads", "0",
    "-pix_fmt", "yuv420p",
]


def h264_encoder_note(width: int, height: int, channels: int = 1) -> str:
    """
    Explain which H.264 encoder will be used, and why.

    Surfaced in the UI because the difference is large: the hardware encoder
    costs almost no CPU, while the software fallback is slower than MJPEG at
    high resolution — the opposite of what "H.264 is more efficient" suggests.

    Never runs the test encode itself: it takes about a second, and the UI
    calls this on every settings change. A resolution not yet tested is
    reported as such; the test runs the first time H.264 is recorded or
    measured there.
    """
    if not ENABLE_HARDWARE_H264:
        return "software encoder — hardware encoding disabled in constants.py"
    if width > HARDWARE_H264_MAX_WIDTH or height > HARDWARE_H264_MAX_HEIGHT:
        return (f"software encoder — the Pi's hardware H.264 encoder only "
                f"handles up to {HARDWARE_H264_MAX_WIDTH}x1080, and this is "
                f"{width}x{height}. Expect it to be SLOWER than MJPEG here.")
    tested = _HARDWARE_H264_CACHE.get((width, height, channels))
    if tested is None:
        return ("hardware encoder if it passes a test encode, run the first "
                "time H.264 is recorded or measured here; software otherwise")
    if tested:
        return "hardware encoder (fast, negligible CPU)"
    return "software encoder — the hardware encoder failed a test encode here"


class HardwareEncoderStartError(RuntimeError):
    """
    The hardware H.264 encoder failed as ffmpeg started. It has already been
    disabled for this configuration, so a retry uses the software encoder.
    """


class FFmpegVideoWriter:
    """
    Writes frames by piping them to ffmpeg.

    Replaces cv2.VideoWriter for video formats because it unlocks two things
    OpenCV cannot offer on a Pi:

      MJPEG  — ffmpeg's encoder is multithreaded, so JPEG compression spreads
               across all four cores instead of saturating the one writer
               thread. This is the only lever available for MJPEG, which has
               no hardware encoder on the Pi.

      H.264  — `h264_v4l2m2m` runs on the Pi's dedicated encoder block rather
               than the CPU, which is dramatically faster at high resolution.
               (OpenCV's only option on the Pi is the `mp4v` fourcc: a
               software MPEG-4 Part 2 encoder, not H.264.)

    Raw frames are written to ffmpeg's stdin. That write blocks if ffmpeg falls
    behind, which is the correct backpressure: it fills our bounded queue, and
    the capture thread then counts honest drops rather than silently buffering.
    """

    STARTUP_CHECK_S = 1.0

    def __init__(self, settings: RecordingSettings):
        import subprocess
        self._subprocess = subprocess

        self._expected_size = (settings.frame_width, settings.frame_height)
        self._channels      = settings.channels
        pixel_format        = "gray" if settings.channels == 1 else "bgr24"

        settings.output_dir.mkdir(parents=True, exist_ok=True)

        encoder_arguments  = self._encoder_arguments(settings)
        self._used_hardware = "h264_v4l2m2m" in encoder_arguments
        self._settings_key  = (settings.frame_width, settings.frame_height,
                               settings.channels)

        command = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-y",                                  # overwrite; UI already confirmed
            "-f", "rawvideo",
            "-pix_fmt", pixel_format,
            "-s", f"{settings.frame_width}x{settings.frame_height}",
            "-r", f"{settings.fps}",
            "-i", "-",                             # read frames from stdin
        ] + encoder_arguments + [str(settings.video_file)]

        # stderr goes to a file rather than a pipe: nothing reads a pipe
        # during recording, and once its buffer filled ffmpeg would block.
        self._stderr_file = tempfile.TemporaryFile()
        self._process = subprocess.Popen(
            command,
            stdin  = subprocess.PIPE,
            stdout = subprocess.DEVNULL,
            stderr = self._stderr_file,
        )
        self._command = command

        # ffmpeg validates its arguments and encoder as it starts, so a bad
        # choice makes it exit before any frame is sent. On a Pi 4 that takes
        # about 0.45 s, so wait up to STARTUP_CHECK_S for an early exit. A
        # healthy ffmpeg never exits here, so this always waits the full time.
        # Catching the failure now lets make_writer fall back to another
        # writer instead of a broken pipe on the first write.
        try:
            self._process.wait(timeout=self.STARTUP_CHECK_S)
        except subprocess.TimeoutExpired:
            pass
        if self._process.poll() is not None:
            message = "ffmpeg failed to start:\n" + self._stderr_text()
            self._stderr_file.close()
            if self._used_hardware:
                disable_hardware_h264(*self._settings_key)
                raise HardwareEncoderStartError(message)
            raise RuntimeError(message)

    @staticmethod
    def _encoder_arguments(settings: RecordingSettings) -> list:
        """
        Encoder flags for the chosen format.

        H.264 uses the same constants the probe tests with, so what gets
        probed and what gets run can never diverge.
        """
        if settings.output_format is formats.H264:
            if hardware_h264_available(settings.frame_width,
                                       settings.frame_height,
                                       settings.channels):
                return list(_HARDWARE_H264_ARGUMENTS)
            # Slower than MJPEG at high resolution — see h264_encoder_note.
            return list(_SOFTWARE_H264_ARGUMENTS)

        # MJPEG: -q:v 3 is visually lossless; -threads 0 uses every core
        return ["-c:v", "mjpeg", "-q:v", "3", "-threads", "0"]

    def write(self, frame: np.ndarray, frame_index: int) -> None:
        if frame_index == 0:
            actual_height, actual_width = frame.shape[:2]
            if (actual_width, actual_height) != self._expected_size:
                raise ValueError(
                    f"Frame size {actual_width}x{actual_height} does not match "
                    f"the video's {self._expected_size[0]}x{self._expected_size[1]}."
                )

        # The pipe reads straight from the frame's memory; ascontiguousarray
        # copies only in the rare case the frame is not contiguous already.
        frame = np.ascontiguousarray(frame)

        try:
            self._process.stdin.write(memoryview(frame).cast("B"))
        except BrokenPipeError:
            self._process.wait()
            message = self._stderr_text()

            # If the hardware encoder failed despite passing its probe, stop
            # choosing it for this configuration. The next attempt then uses
            # the software encoder rather than repeating the same failure.
            if self._used_hardware:
                disable_hardware_h264(*self._settings_key)
                raise RuntimeError(
                    "The hardware H.264 encoder failed during recording and "
                    "has been disabled for this resolution. Try again — it "
                    "will use the software encoder.\n\n" + message
                )
            raise RuntimeError("ffmpeg exited during recording:\n" + message)

    def close(self) -> None:
        """Close the pipe and wait for ffmpeg to finalize the container."""
        if self._process.stdin:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        # Finalizing can take a moment on a long recording; the container's
        # index is written here, so cutting it short corrupts the file.
        try:
            self._process.wait(timeout=120)
        except self._subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
            raise RuntimeError(
                "ffmpeg did not finish writing the video within 120 s and was "
                "stopped; the file is probably incomplete."
            )
        finally:
            message = self._stderr_text()
            self._stderr_file.close()
        if self._process.returncode != 0:
            raise RuntimeError(
                f"ffmpeg exited with code {self._process.returncode} while "
                f"finishing the video:\n{message}"
            )

    def _stderr_text(self, limit: int = 500) -> str:
        """The first `limit` characters ffmpeg wrote to stderr."""
        try:
            self._stderr_file.seek(0)
            return self._stderr_file.read(limit).decode(errors="replace")
        except (OSError, ValueError):     # ValueError: file already closed
            return ""


# =============================================================================
# Parallel image stack writer
# =============================================================================

class ParallelImageStackWriter:
    """
    Writes each frame as a separate image, encoding across several threads.

    Image stacks have no hardware encoder on the Pi, so parallelism is the only
    way to use more than one core. Frames are independent files, which makes
    this straightforward — unlike a video container, where frames must be
    written in order.

    Threads rather than processes because OpenCV releases the GIL during
    imwrite, so its encoding genuinely runs in parallel; processes would add
    the cost of pickling a full-resolution frame to each worker.
    """

    def __init__(self, settings: RecordingSettings,
                 worker_count: int = IMAGE_STACK_WORKERS):
        import cv2
        from concurrent.futures import ThreadPoolExecutor
        import threading
        self._cv2       = cv2
        self._settings  = settings
        self._extension = settings.file_extension
        settings.output_dir.mkdir(parents=True, exist_ok=True)

        # Confirm an image can actually be written here BEFORE the recording
        # starts. imwrite reports failure by returning False, and in the
        # parallel writer that happens on a worker thread — so without this an
        # unwritable directory or an unsupported format would only be
        # discovered after a whole recording had run, having produced nothing.
        probe_file = settings.output_dir / f".write_probe{self._extension}"
        try:
            if not cv2.imwrite(str(probe_file), np.zeros((8, 8), dtype=np.uint8)):
                raise OSError(
                    f"Cannot write {self._extension} files to "
                    f"{settings.output_dir}. The format may be unsupported by "
                    f"this OpenCV build, or the directory may not be writable."
                )
        finally:
            try:
                probe_file.unlink(missing_ok=True)
            except OSError:
                pass


        # Three workers by default: the Pi 4 has four cores, and capture plus
        # the main thread need headroom. More workers would contend rather
        # than help.
        self._flags   = image_encode_flags(cv2, self._extension)
        self._pool    = ThreadPoolExecutor(max_workers=worker_count)
        self._error   = None

        # ThreadPoolExecutor's queue is unbounded, so submit() always returns
        # instantly no matter how far behind the workers are. Left unchecked
        # that would buffer full-resolution frames in RAM until the Pi ran out,
        # and would also hide the true encode cost from any timing around
        # write(). A semaphore caps how many frames may be in flight, so
        # write() blocks once the workers are saturated — the same honest
        # backpressure the video path gets from ffmpeg's pipe.
        self._slots = threading.Semaphore(worker_count * 2)

    def write(self, frame: np.ndarray, frame_index: int) -> None:
        # Surface an earlier worker failure immediately rather than letting a
        # whole recording run against a directory that cannot be written. The
        # capture loop turns this into a visible recording error.
        if self._error is not None:
            raise self._error

        image_file = (
            self._settings.output_dir
            / f"{self._settings.file_name}_{frame_index + 1:05d}{self._extension}"
        )
        # Blocks when the pool is saturated, which is what makes the queue
        # bounded and the timing meaningful.
        self._slots.acquire()
        # Frames are handed off by reference; the capture thread never reuses a
        # buffer while it is still in flight, so no copy is needed here.
        self._pool.submit(self._write_one, frame, image_file)

    def _encode_flags(self) -> list:
        """Per-format encoder flags; see image_encode_flags."""
        return self._flags

    def _write_one(self, frame: np.ndarray, image_file) -> None:
        try:
            # Color frames are already BGR (picamera2's RGB888), as OpenCV expects.
            # imwrite returns False rather than raising on most failures —
            # an unwritable path, an unsupported extension, a full disk — so
            # the result must be checked or frames vanish silently.
            if not self._cv2.imwrite(str(image_file), frame, self._encode_flags()):
                raise OSError(
                    f"Could not write {image_file.name}. The format may be "
                    f"unsupported for this image, or the disk may be full."
                )
        except Exception as write_error:
            if self._error is None:      # keep the FIRST error, it explains the rest
                self._error = write_error
        finally:
            self._slots.release()

    def close(self) -> None:
        """Wait for every queued frame to finish writing."""
        self._pool.shutdown(wait=True)
        if self._error is not None:
            raise self._error


# =============================================================================
# Throughput calibration: what each format can actually sustain
# =============================================================================
#
# A recording's frame rate is capped by whichever of three stages is slowest:
#
#   camera   — sensor readout, ISP processing, and our crop/copy
#   encoding — compressing each frame (CPU, or the hardware H.264 block)
#   SD card  — writing the encoded bytes
#
# Which one binds depends on resolution, color mode AND format, so each
# format is measured separately. The first two are measured by running the
# real recording machinery — capture thread, queue, writer thread — flat out,
# because they overlap in a real recording: timing them back to back in one
# loop reports roughly 1/(capture + encode) where a recording reaches
# 1/max(capture, encode), which can understate the true rate by half.
#
# The SD card is NOT measured inside that run. A few seconds of writes land in
# the operating system's RAM cache before reaching the card, so a short run
# cannot see the card's real speed. Its cap is computed instead from the
# measured bytes per frame and the card's write speed (Settings -> Recalibrate
# write speed), which forces data to the card with fsync.

def measure_format_throughput(
    camera,
    settings,
    sensor_max_fps: float,
    warmup_seconds: float = 1.0,
    window_seconds: float = 3.0,
    wait=time.sleep,
) -> dict:
    """
    Run one format flat out and report what the camera and encoder sustain,
    plus how many bytes a frame takes on disk.

    `wait` is how this function pauses between phases. The UI passes a version
    that keeps processing events, so the window stays responsive during the
    roughly five seconds each format takes.

    Raises RuntimeError if the format cannot record at all.
    """
    import tempfile
    from dataclasses import replace

    # The camera must run at the sensor mode's maximum, not at whatever frame
    # rate is selected in the UI, or the measurement reports that selection
    # back instead of the real ceiling.
    previous_fps = getattr(camera, "_target_fps", None)
    camera.set_capture_fps(sensor_max_fps)

    try:
        last_error = None
        # Two attempts: if the hardware H.264 encoder fails once frames stream,
        # it marks itself unavailable, and the retry uses the software encoder.
        for _attempt in range(2):
            # Written inside the save directory so encoding happens on the real
            # drive's filesystem; hidden and removed afterwards.
            with tempfile.TemporaryDirectory(
                dir=settings.save_dir, prefix=".throughput_probe_"
            ) as temporary_dir:
                probe_settings = replace(
                    settings,
                    save_dir   = Path(temporary_dir),
                    file_name  = "throughput_probe",
                    duration_s = None,
                    # Pace the capture loop above the sensor's maximum so the
                    # camera itself sets the rate, not our scheduler
                    fps        = sensor_max_fps * 1.5,
                )
                session = RecordingSession(camera, probe_settings)
                try:
                    session.start()
                    wait(warmup_seconds)
                    before = _snapshot(session.stats)
                    wait(window_seconds)
                    after = _snapshot(session.stats)
                finally:
                    session.request_stop()
                    deadline = time.perf_counter() + 60
                    while not session.is_finished and time.perf_counter() < deadline:
                        wait(0.05)
                    summary = session.finalize()

                if summary.get("error"):
                    last_error = summary["error"]
                    continue

                output_bytes = _probe_output_bytes(probe_settings)

            frames_written = summary.get("frames_written", 0)
            if frames_written == 0 or after["time"] <= before["time"]:
                last_error = "no frames were written"
                continue

            elapsed       = after["time"] - before["time"]
            offered       = (after["captured"] + after["dropped"]
                             - before["captured"] - before["dropped"])
            written       = after["written"] - before["written"]
            dropped       = after["dropped"] - before["dropped"]
            camera_fps    = offered / elapsed
            written_fps   = written / elapsed

            # Frames dropped at the queue mean capture outran the writer, so
            # encoding is the limit. Otherwise the writer kept up and the
            # camera set the pace.
            pipeline_limit = "encoding" if dropped > 0 else "camera"
            pipeline_fps   = min(camera_fps, written_fps) if dropped == 0 else written_fps

            return {
                "pipeline_fps":    round(pipeline_fps, 1),
                "pipeline_limit":  pipeline_limit,
                "camera_fps":      round(camera_fps, 1),
                "bytes_per_frame": int(output_bytes / frames_written),
                "measured_on":     datetime.now().strftime("%Y-%m-%d"),
            }

        raise RuntimeError(f"Could not record in this format: {last_error}")
    finally:
        if previous_fps is not None:
            camera.set_capture_fps(previous_fps)


def _snapshot(stats) -> dict:
    """Read the live counters at one instant."""
    return {
        "time":     time.perf_counter(),
        "captured": stats.frames_captured,
        "dropped":  stats.frames_dropped,
        "written":  stats.frames_written,
    }


def _probe_output_bytes(settings) -> int:
    """Total size of the media a probe produced (excluding the timestamp CSV)."""
    if settings.is_image_stack:
        pattern = f"{settings.file_name}_*{settings.file_extension}"
        return sum(f.stat().st_size for f in settings.output_dir.glob(pattern))
    return settings.video_file.stat().st_size if settings.video_file.exists() else 0


def capacity_for(measurement: dict, write_speed_mbs, free_space_gb,
                 selected_fps: float) -> dict:
    """
    Combine a stored measurement with the card's current state.

    Kept separate from the measurement so the table stays right when things
    change that do not require re-measuring: recalibrating write speed, or the
    card filling up.

    Returns max_fps, what limits it, and how many minutes fit on the card at
    the rate a recording would actually run (the selected rate, unless that
    exceeds the maximum).
    """
    max_fps = measurement["pipeline_fps"]
    limit   = measurement["pipeline_limit"]
    bytes_per_frame = measurement.get("bytes_per_frame", 0)

    if write_speed_mbs and bytes_per_frame > 0:
        from constants import BENCHMARK_SAFETY_MARGIN
        card_bytes_per_second = write_speed_mbs * 1024 * 1024 * BENCHMARK_SAFETY_MARGIN
        card_fps = card_bytes_per_second / bytes_per_frame
        if card_fps < max_fps:
            max_fps, limit = card_fps, "SD card"

    recording_fps = min(selected_fps, max_fps) if selected_fps > 0 else max_fps
    minutes = None
    if free_space_gb and bytes_per_frame > 0 and recording_fps > 0:
        free_bytes = free_space_gb * 1024 ** 3
        minutes = free_bytes / (bytes_per_frame * recording_fps * 60)

    return {
        "max_fps":       round(max_fps, 1),
        "limit":         limit,
        "recording_fps": recording_fps,
        "minutes":       minutes,
        "mb_per_frame":  bytes_per_frame / 1024 / 1024,
    }


def encoder_signature(output_format: OutputFormat) -> str:
    """
    The encoder settings that affect speed and size for one format.

    Part of the cache key, so changing an encoder setting in constants.py
    shows the format as unmeasured instead of reusing figures that described
    a different encoder.
    """
    from constants import PNG_MODE, TIFF_COMPRESSION, ENABLE_HARDWARE_H264
    if output_format is formats.PNG:
        return f"png-{PNG_MODE}"
    if output_format is formats.TIFF:
        return f"tiff-{TIFF_COMPRESSION}"
    if output_format is formats.H264:
        return f"h264-hw{int(ENABLE_HARDWARE_H264)}"
    return output_format.key


def throughput_cache_key(width: int, height: int, channels: int,
                         output_format: OutputFormat) -> str:
    """
    Identify one measurable combination.

    Framerate is deliberately absent: the measurement finds the CEILING, which
    does not depend on the rate selected.
    """
    color = "gray" if channels == 1 else "color"
    return f"{width}x{height}_{color}_{encoder_signature(output_format)}"


def remove_previous_stack_frames(settings: RecordingSettings) -> int:
    """
    Delete the frames an earlier image stack of the same name left in its
    folder, so an overwritten stack cannot end up mixing old and new frames.

    Only files named like stack frames of this file name ({file_name}_NNNNN
    with an image-stack extension) are removed; anything else in the folder
    is left alone. Returns how many files were removed.
    """
    if not settings.output_dir.is_dir():
        return 0
    frame_name = re.compile(rf"{re.escape(settings.file_name)}_\d+")
    extensions = {f.extension for f in formats.OUTPUT_FORMATS if f.is_image_stack}
    removed = 0
    for path in settings.output_dir.iterdir():
        if path.suffix in extensions and frame_name.fullmatch(path.stem) and path.is_file():
            path.unlink()
            removed += 1
    return removed


# =============================================================================
# Writer selection
# =============================================================================

def make_writer(settings: RecordingSettings):
    """
    Return the appropriate writer for the selected output format.

    Video goes through ffmpeg (multithreaded MJPEG, hardware H.264 where the
    resolution allows); image stacks go through a small thread pool. Both fall
    back to the single-threaded OpenCV path if anything is unavailable, so a
    missing ffmpeg degrades performance rather than breaking recording.

    Fallbacks are recorded on the writer as `fallback_reason` rather than
    passing silently: dropping to the slow path can halve the achievable
    frame rate, and finding out from a performance mystery later is far worse
    than being told at the time.
    """
    if settings.is_image_stack:
        writer = ParallelImageStackWriter(settings)
        writer.fallback_reason = None
        return writer

    hardware_note = None
    try:
        try:
            writer = FFmpegVideoWriter(settings)
        except HardwareEncoderStartError as hardware_error:
            # Hardware H.264 is now disabled for this configuration, so this
            # second attempt runs ffmpeg with the software encoder.
            hardware_note = (f"hardware H.264 encoder failed to start "
                             f"({str(hardware_error)[:200]}); using software H.264")
            writer = FFmpegVideoWriter(settings)
        writer.fallback_reason = hardware_note
        return writer
    except Exception as ffmpeg_error:
        writer = VideoWriter(settings)
        if settings.output_format is formats.H264:
            fallback = ("OpenCV's MPEG-4 Part 2 encoder — the file is NOT H.264, "
                        "and encoding is single-threaded and slower")
        else:
            fallback = "OpenCV, which is single-threaded and slower"
        writer.fallback_reason = (
            f"ffmpeg unavailable ({str(ffmpeg_error)[:200]}); using {fallback}"
        )
        return writer


# =============================================================================
# Recording session — manages capture and writer threads
# =============================================================================

class RecordingSession:
    """
    Runs one recording from start to finish.

    Usage:
        session = RecordingSession(camera, settings)
        session.start()
        ...  # poll session.stats for live UI updates
        summary = session.stop()
    """

    def __init__(self, camera, settings: RecordingSettings,
                 queue_size: int = FRAME_QUEUE_SIZE,
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
        """Open the writer, reconfigure the camera, and launch both threads."""
        # Reconfigure the main stream to match the recording's color mode
        # BEFORE capture starts. For a grayscale recording this means the
        # camera skips full-color ISP processing entirely rather than
        # capturing color and discarding it afterward — see
        # PiCamera.prepare_for_recording for why this matters.
        self._camera.prepare_for_recording(self._settings.channels)

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

    @property
    def writer_note(self) -> str | None:
        """Why the writer fell back to a slower or different encoder, if it did."""
        return getattr(self._writer, "fallback_reason", None)

    @property
    def queue_capacity(self) -> int:
        """How many frames the buffer between capture and writing can hold."""
        return self._queue.maxsize

    def finalize(self) -> dict:
        """
        Close the writer and return the summary. Call only once is_finished is
        True, otherwise this blocks until the threads end.
        """
        if self._capture_thread:
            self._capture_thread.join(timeout=5.0)
        if self._writer_thread:
            self._writer_thread.join(timeout=60.0)

        # A failure while closing (ffmpeg finishing the container, image
        # workers reporting a write error) is recorded like any other
        # recording error, so the summary and frame counts survive it.
        if self._writer:
            try:
                self._writer.close()
            except Exception as close_error:
                if self._error is None:
                    self._error = close_error

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
            "writer_note":        self.writer_note,
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

            # A full queue means this frame would be dropped anyway, so the
            # camera is asked not to copy it out of its buffer at all.
            queue_full = self._queue.full()
            try:
                frame, preview_frame = self._camera.capture_frame(
                    self._settings.channels, want_preview, discard=queue_full
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
                if frame is None:
                    raise queue.Full
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
        """
        Pull frames off the queue and write them until sentinel is received.

        After a write error the loop keeps consuming (and discarding) frames
        until the sentinel. Stopping early would leave the queue full, and the
        capture thread would then block forever trying to enqueue the sentinel.
        """
        write_failed = False
        while True:
            frame = self._queue.get()
            if frame is None:      # sentinel: capture finished and queue drained
                break
            if write_failed:
                continue
            try:
                self._writer.write(frame, self.stats.frames_written)
                self.stats.frames_written += 1
            except Exception as write_error:
                self._error   = write_error
                self._running = False
                write_failed  = True
