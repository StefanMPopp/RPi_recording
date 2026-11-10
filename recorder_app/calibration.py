"""
calibration.py
==============
Image analysis behind Settings → Calibrate camera. The window itself is in
calibration_window.py; nothing here depends on Qt.

  - Animal detection: dark blobs that differ from a background image. Dark
    things that never move (tape, the arena rim, shadows) are part of the
    background image, so they are never counted as animals.
  - Brightness of background and animals, and how much is clipped
  - Speed: blob centroids followed between frames, as a distribution
  - Aperture sweep: edge width (sharpness) and evenness across the frame
  - Reading recordings made by this app, for offline speed analysis

All analysis runs on frames at most PREVIEW_WIDTH wide: the live preview
stream, or recordings scaled down to that width.
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import yaml

from constants import (
    PREVIEW_WIDTH,
    CALIBRATION_DARKER_FRACTION, CALIBRATION_DARKER_LEVELS, CALIBRATION_MIN_BLOB_PX,
    CALIBRATION_BACKGROUND_FRAMES, CALIBRATION_BACKGROUND_INTERVAL_S,
    CALIBRATION_SPEED_STEP_S, CALIBRATION_MAX_VIDEO_S,
)

# Pixel values treated as clipped: at or above CLIPPED_HIGH the sensor or
# ISP saturated, at or below CLIPPED_LOW detail is lost in black
CLIPPED_HIGH = 254
CLIPPED_LOW  = 1

# Region of the frame to analyze: normalized (x, y, width, height), or None
# for the whole frame
Region = tuple[float, float, float, float] | None


def region_slices(region: Region, shape) -> tuple[slice, slice]:
    """Row and column slices of `shape` covered by a normalized region."""
    height, width = shape[:2]
    if region is None:
        return slice(0, height), slice(0, width)
    x, y, region_width, region_height = region
    left   = min(width - 1,  max(0, int(round(x * width))))
    top    = min(height - 1, max(0, int(round(y * height))))
    right  = max(left + 1, min(width,  int(round((x + region_width)  * width))))
    bottom = max(top + 1,  min(height, int(round((y + region_height) * height))))
    return slice(top, bottom), slice(left, right)


def to_gray(frame: np.ndarray) -> np.ndarray:
    """Grayscale view of a preview frame, which is RGB in color mode."""
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)


# =============================================================================
# Background image and animal detection
# =============================================================================

class Background:
    """
    What the arena looks like without moving animals: the per-pixel median
    of frames spread out in time. An animal is anywhere the current frame is
    clearly darker than this.
    """

    def __init__(self, image: np.ndarray):
        self.image = image
        # Darker by CALIBRATION_DARKER_FRACTION of the background, and by at
        # least CALIBRATION_DARKER_LEVELS where the background is dark
        self.threshold = np.maximum(
            CALIBRATION_DARKER_LEVELS,
            image.astype(np.float32) * CALIBRATION_DARKER_FRACTION,
        ).astype(np.uint8)

    @classmethod
    def from_samples(cls, samples: list[np.ndarray], shape) -> "Background":
        """
        Build from half-resolution samples (frame[::2, ::2]) of frames of
        `shape`. The median of a full-resolution stack takes a third of a
        second on a Pi 4, a quarter-size one a quarter of that. The
        upscaled image is up to a pixel off at sharp edges, which the
        opening in detect_animals removes again.
        """
        median = np.median(np.stack(samples), axis=0).astype(np.uint8)
        image = cv2.resize(median, (shape[1], shape[0]),
                           interpolation=cv2.INTER_NEAREST)
        return cls(image)


class LiveBackground:
    """
    Background image for the live preview, kept current as the scene
    changes: one sample every CALIBRATION_BACKGROUND_INTERVAL_S, the median
    of the last CALIBRATION_BACKGROUND_FRAMES, rebuilt every few seconds.
    """

    _REBUILD_INTERVAL_S = 2.0

    def __init__(self):
        self.background: Background | None = None
        self._samples: deque = deque(maxlen=CALIBRATION_BACKGROUND_FRAMES)
        self._shape = None
        self._last_sample_s: float | None = None
        self._last_rebuild_s: float | None = None

    def reset(self) -> None:
        """Start over, e.g. after the exposure changed."""
        self.background = None
        self._samples.clear()
        self._last_sample_s = self._last_rebuild_s = None

    @property
    def progress(self) -> float:
        """How far the first background image is, 0 to 1."""
        if self.background is not None:
            return 1.0
        return len(self._samples) / self._samples.maxlen

    def add(self, gray: np.ndarray, time_s: float) -> None:
        if gray.shape != self._shape:
            self.reset()
            self._shape = gray.shape
        if self._last_sample_s is None \
                or time_s - self._last_sample_s >= CALIBRATION_BACKGROUND_INTERVAL_S:
            self._samples.append(gray[::2, ::2].copy())
            self._last_sample_s = time_s
        # The first image waits for a full window, so animals that moved
        # during it are not part of it
        if len(self._samples) < self._samples.maxlen:
            return
        if self._last_rebuild_s is None \
                or time_s - self._last_rebuild_s >= self._REBUILD_INTERVAL_S:
            self.background = Background.from_samples(list(self._samples), gray.shape)
            self._last_rebuild_s = time_s


@dataclass
class Blob:
    x:    float      # centroid, in frame pixels
    y:    float
    area: int        # in frame pixels


@dataclass
class Detection:
    blobs: list[Blob]
    # Animal pixels inside the analyzed region (uint8, 0 or 1), and where
    # that region starts in the frame
    mask:   np.ndarray
    origin: tuple[int, int]      # (top, left)


_OPEN_KERNEL = np.ones((3, 3), np.uint8)


def detect_animals(gray: np.ndarray, background: Background,
                   region: Region = None) -> Detection:
    """Dark blobs that are not part of the background, inside the region."""
    rows, columns = region_slices(region, gray.shape)
    darker = cv2.subtract(background.image[rows, columns], gray[rows, columns])
    mask = cv2.compare(darker, background.threshold[rows, columns], cv2.CMP_GT)
    # Opening removes single-pixel noise and the thin seams an upscaled
    # background leaves along sharp edges
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _OPEN_KERNEL)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)

    blobs = []
    keep = np.zeros(count, np.uint8)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < CALIBRATION_MIN_BLOB_PX:
            continue
        keep[label] = 1
        blobs.append(Blob(x=float(centroids[label][0]) + columns.start,
                          y=float(centroids[label][1]) + rows.start,
                          area=area))
    return Detection(blobs=blobs, mask=keep[labels], origin=(rows.start, columns.start))


# =============================================================================
# Brightness levels
# =============================================================================

@dataclass
class Levels:
    background:   float | None   # typical background value in the region
    animal:       float | None   # typical value of animal pixels
    clipped_pct:  float          # region pixels at CLIPPED_HIGH or above
    crushed_pct:  float | None   # animal pixels at CLIPPED_LOW or below


def measure_levels(gray: np.ndarray, region: Region,
                   detection: Detection | None) -> Levels:
    rows, columns = region_slices(region, gray.shape)
    pixels = gray[rows, columns]
    clipped_pct = 100.0 * np.count_nonzero(pixels >= CLIPPED_HIGH) / pixels.size

    animal = crushed_pct = None
    if detection is not None and detection.blobs:
        animal_mask = detection.mask.astype(bool)
        animal_pixels = pixels[animal_mask]
        animal = float(np.median(animal_pixels))
        crushed_pct = 100.0 * np.count_nonzero(animal_pixels <= CLIPPED_LOW) / animal_pixels.size
        # Every other pixel samples the background well enough, at a
        # quarter of the cost
        background_pixels = pixels[::2, ::2][~animal_mask[::2, ::2]]
    else:
        background_pixels = pixels[::2, ::2]
    background = float(np.median(background_pixels)) if background_pixels.size else None
    return Levels(background=background, animal=animal,
                  clipped_pct=clipped_pct, crushed_pct=crushed_pct)


# =============================================================================
# Speed
# =============================================================================

@dataclass
class SpeedSummary:
    steps:    int      # animal movements measured
    p95_mm_s: float
    p99_mm_s: float
    max_mm_s: float


class SpeedTracker:
    """
    Speeds of animals between frames about CALIBRATION_SPEED_STEP_S apart.

    No identities are kept: each blob is matched to the nearest blob in the
    previous frame, and the match is only used when it is unambiguous —
    each is the other's nearest, the next candidate is at least twice as
    far, and both are about the same size. Animals touching each other
    form one large blob that matches nothing, so encounters drop out
    rather than producing false jumps. Steps shorter than a pixel are
    centroid jitter of a resting animal and are left out, so the
    percentiles describe the animals while they move.
    """

    _AREA_RATIO = (0.6, 1.6)     # blob area may change this much between frames
    _MIN_STEP_PX = 1.0

    def __init__(self, px_per_mm: float):
        self._px_per_mm = px_per_mm
        self._previous: tuple[float, list[Blob]] | None = None
        self.speeds_mm_s: list[float] = []

    def add(self, time_s: float, blobs: list[Blob]) -> None:
        if self._previous is None:
            self._previous = (time_s, blobs)
            return
        previous_time_s, previous_blobs = self._previous
        interval_s = time_s - previous_time_s
        if interval_s < 0.7 * CALIBRATION_SPEED_STEP_S:
            return                  # keep the earlier frame as the reference
        self._previous = (time_s, blobs)
        if interval_s > 3 * CALIBRATION_SPEED_STEP_S:
            return                  # a gap: too much can happen in between
        for before, after in self._match(previous_blobs, blobs):
            step_px = float(np.hypot(after.x - before.x, after.y - before.y))
            if step_px >= self._MIN_STEP_PX:
                self.speeds_mm_s.append(step_px / self._px_per_mm / interval_s)

    def _match(self, before: list[Blob], after: list[Blob]) -> list[tuple[Blob, Blob]]:
        if not before or not after:
            return []
        before_xy = np.array([(blob.x, blob.y) for blob in before])
        after_xy  = np.array([(blob.x, blob.y) for blob in after])
        distance = np.hypot(before_xy[:, None, 0] - after_xy[None, :, 0],
                            before_xy[:, None, 1] - after_xy[None, :, 1])
        matches = []
        for row in range(len(before)):
            column = int(np.argmin(distance[row]))
            if int(np.argmin(distance[:, column])) != row:
                continue
            nearest = distance[row, column]
            others = np.concatenate([np.delete(distance[row], column),
                                     np.delete(distance[:, column], row)])
            if others.size and nearest > 0.5 * others.min():
                continue
            area_ratio = after[column].area / before[row].area
            if not self._AREA_RATIO[0] <= area_ratio <= self._AREA_RATIO[1]:
                continue
            matches.append((before[row], after[column]))
        return matches

    def summary(self) -> SpeedSummary | None:
        if not self.speeds_mm_s:
            return None
        speeds = np.array(self.speeds_mm_s)
        p95, p99 = np.percentile(speeds, (95, 99))
        return SpeedSummary(steps=len(speeds), p95_mm_s=float(p95), p99_mm_s=float(p99),
                            max_mm_s=float(speeds.max()))


# =============================================================================
# Aperture sweep
# =============================================================================

# Cells of a 3×3 grid over the region that are measured: (row, column)
APERTURE_CELLS = {
    "center":       (1, 1),
    "top left":     (0, 0), "top right":    (0, 2),
    "bottom left":  (2, 0), "bottom right": (2, 2),
}

# Darkest-to-brightest difference a cell needs to count as holding a target
_MIN_TARGET_CONTRAST = 60
_EDGE_KERNEL = np.ones((5, 5), np.uint8)


@dataclass
class ApertureResult:
    edge_width_px: dict[str, float | None]   # per cell; None = no target found
    white_level:   dict[str, float]

    @property
    def center_edge_px(self) -> float | None:
        return self.edge_width_px["center"]

    @property
    def worst_corner_edge_px(self) -> float | None:
        corners = [width for name, width in self.edge_width_px.items()
                   if name != "center"]
        if any(width is None for width in corners):
            return None
        return max(corners)

    @property
    def evenness(self) -> float:
        """Darkest corner's white as a fraction of the center's."""
        corners = [level for name, level in self.white_level.items() if name != "center"]
        return min(corners) / max(1.0, self.white_level["center"])

    @property
    def missing_targets(self) -> list[str]:
        return [name for name, width in self.edge_width_px.items() if width is None]


def measure_aperture(gray: np.ndarray, region: Region) -> ApertureResult:
    rows, columns = region_slices(region, gray.shape)
    area = gray[rows, columns]
    cell_height, cell_width = area.shape[0] // 3, area.shape[1] // 3
    edge_width_px, white_level = {}, {}
    for name, (row, column) in APERTURE_CELLS.items():
        cell = area[row * cell_height:(row + 1) * cell_height,
                    column * cell_width:(column + 1) * cell_width]
        edge_width_px[name], white_level[name] = _edge_width(cell)
    return ApertureResult(edge_width_px=edge_width_px, white_level=white_level)


def _edge_width(cell: np.ndarray) -> tuple[float | None, float]:
    """
    How many pixels a black-to-white edge in this cell is spread over, and
    the cell's white level.

    The edges are found from the print itself: a band around everything
    darker than halfway between black and white. Within that band, the
    steepest gradients (90th percentile) belong to the edges, and the
    full black-to-white step divided by that gradient is the width of the
    edge: 1 px for a perfectly sharp image, more as blur spreads it. Being
    relative to the cell's own contrast, it does not depend on exposure.
    """
    pixels = cell.astype(np.float32)
    black, white = np.percentile(pixels, (0.5, 98))
    if white - black < _MIN_TARGET_CONTRAST:
        return None, float(white)
    print_mask = (pixels < (black + white) / 2).astype(np.uint8)
    edge_band = cv2.dilate(print_mask, _EDGE_KERNEL) - cv2.erode(print_mask, _EDGE_KERNEL)
    # Forward differences: a ramp over w pixels rises (white - black) / w per pixel
    gradient = np.hypot(np.abs(np.diff(pixels, axis=1))[:-1, :],
                        np.abs(np.diff(pixels, axis=0))[:, :-1])
    band_gradients = gradient[edge_band[:-1, :-1] > 0]
    if band_gradients.size < 200:
        return None, float(white)
    steepest = float(np.percentile(band_gradients, 90))
    return (white - black) / max(steepest, 1e-6), float(white)


# =============================================================================
# Recordings
# =============================================================================

VIDEO_EXTENSIONS = (".avi", ".mp4")
STACK_EXTENSIONS = (".tiff", ".tif", ".png")


class RecordingReader:
    """
    Frames of a recording made by this app, with their times and scale.

    `path` is a video file, an image of a stack, or a stack's folder. The
    frame rate, scale and frame times come from the files the app writes
    beside the footage (see metadata.py and record._write_frame_times);
    without a metadata file the scale is None and the frame rate is the
    video container's.
    """

    def __init__(self, path: Path):
        path = Path(path)
        self._video: cv2.VideoCapture | None = None
        self._images: list[Path] = []
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            self.name = path.name
            metadata_file    = path.with_name(f"{path.stem}_metadata.yaml")
            frame_times_file = path.with_name(f"{path.stem}_frame_times.csv")
            self._video_path = path
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise ValueError(f"Cannot open {path.name}")
            self.frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            container_fps    = capture.get(cv2.CAP_PROP_FPS) or None
            capture.release()
        else:
            folder = path if path.is_dir() else path.parent
            self.name = folder.name
            self._images = sorted(image for image in folder.iterdir()
                                  if image.suffix.lower() in STACK_EXTENSIONS)
            if not self._images:
                raise ValueError(f"No TIFF or PNG images in {folder}")
            metadata_file    = folder / "metadata.yaml"
            frame_times_file = folder / "frame_times.csv"
            self.frame_count = len(self._images)
            container_fps    = None

        metadata = {}
        if metadata_file.exists():
            with metadata_file.open() as file_handle:
                metadata = yaml.safe_load(file_handle) or {}
        capture_info = metadata.get("capture") or {}
        self.fps: float | None = (capture_info.get("effective_fps")
                                  or capture_info.get("requested_fps")
                                  or container_fps)
        self.px_per_cm: float | None = (metadata.get("scale") or {}).get("px_per_cm")

        # Exact sensor times, which also account for any dropped frames
        self._frame_times: list[float] | None = None
        if frame_times_file.exists():
            with frame_times_file.open(newline="") as file_handle:
                self._frame_times = [float(row["time_s"]) for row in csv.DictReader(file_handle)]

    def time_s(self, index: int) -> float:
        if self._frame_times is not None and index < len(self._frame_times):
            return self._frame_times[index]
        return index / self.fps

    def _gray(self, frame: np.ndarray) -> np.ndarray:
        return frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def frame(self, index: int) -> np.ndarray | None:
        """One frame by index, grayscale; slow for video, which must seek."""
        if self._video is None and not self._images:
            return None
        if self._images:
            return cv2.imread(str(self._images[index]), cv2.IMREAD_GRAYSCALE)
        self._video.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self._video.read()
        return self._gray(frame) if ok else None

    def frames(self, stride: int, limit: int):
        """(index, grayscale frame) for every stride-th frame below limit."""
        if self._images:
            for index in range(0, limit, stride):
                frame = cv2.imread(str(self._images[index]), cv2.IMREAD_GRAYSCALE)
                if frame is not None:
                    yield index, frame
            return
        self._video.set(cv2.CAP_PROP_POS_FRAMES, 0)
        for index in range(limit):
            if index % stride:
                if not self._video.grab():      # skipped frames are not decoded
                    return
                continue
            ok, frame = self._video.read()
            if not ok:
                return
            yield index, self._gray(frame)

    def __enter__(self) -> "RecordingReader":
        if not self._images:
            self._video = cv2.VideoCapture(str(self._video_path))
        return self

    def __exit__(self, *_exc) -> None:
        if self._video is not None:
            self._video.release()
            self._video = None


def _analysis_size(gray: np.ndarray) -> np.ndarray:
    """Scale a frame down to at most PREVIEW_WIDTH wide, like the live preview."""
    if gray.shape[1] <= PREVIEW_WIDTH:
        return gray
    height = int(round(gray.shape[0] * PREVIEW_WIDTH / gray.shape[1]))
    return cv2.resize(gray, (PREVIEW_WIDTH, height), interpolation=cv2.INTER_AREA)


def analyze_recording_speed(
        reader: RecordingReader, px_per_cm: float,
        progress: Callable[[float, np.ndarray, Detection], None] | None = None,
        canceled: Callable[[], bool] = lambda: False) -> SpeedSummary | None:
    """
    Speed distribution of the animals in a recording, measured as in the
    live preview: frames CALIBRATION_SPEED_STEP_S apart, scaled to the
    preview's width, against a background image of the analyzed span.

    Only the first CALIBRATION_MAX_VIDEO_S seconds are analyzed. `progress`
    is called now and then with the fraction done, the frame and its
    detection. Must be used inside `with reader:`.
    """
    if not reader.fps:
        raise ValueError("The frame rate of this recording is unknown.")
    limit  = min(reader.frame_count, int(CALIBRATION_MAX_VIDEO_S * reader.fps))
    stride = max(1, round(CALIBRATION_SPEED_STEP_S * reader.fps))
    if limit < 2 * stride:
        raise ValueError("The recording is too short to measure speed.")

    samples, shape, scale = [], None, 1.0
    for index in np.linspace(0, limit - 1, CALIBRATION_BACKGROUND_FRAMES).astype(int):
        frame = reader.frame(int(index))
        if frame is None:
            continue
        scale = min(1.0, PREVIEW_WIDTH / frame.shape[1])
        frame = _analysis_size(frame)
        shape = frame.shape
        samples.append(frame[::2, ::2])
    if len(samples) < 3:
        raise ValueError("Could not read frames from this recording.")
    background = Background.from_samples(samples, shape)

    tracker = SpeedTracker(px_per_mm=px_per_cm / 10 * scale)
    for count, (index, frame) in enumerate(reader.frames(stride, limit)):
        if canceled():
            break
        frame = _analysis_size(frame)
        detection = detect_animals(frame, background)
        tracker.add(reader.time_s(index), detection.blobs)
        if progress is not None and count % 5 == 0:
            progress(index / limit, frame, detection)
    return tracker.summary()
