"""
benchmark.py
============
SD card write speed benchmark and storage headroom calculator.

Write speed is measured once and stored in config_app.yaml.
Headroom is computed live from the stored value as the user
changes resolution / fps / format in the UI.
"""

import shutil
import tempfile
import time
from pathlib import Path

from constants import (
    BENCHMARK_FILE_MB,
    BENCHMARK_SAFETY_MARGIN,
    HEADROOM_GREEN_MAX,
    HEADROOM_AMBER_MAX,
)


# =============================================================================
# Write speed benchmark
# =============================================================================

def measure_write_speed_mbs(target_dir: Path) -> float:
    """
    Write a large temporary file to target_dir and return the sustained
    write speed in MB/s.

    Uses a {BENCHMARK_FILE_MB} MB file to capture sustained (not burst) speed.
    The temp file is deleted immediately after measurement.
    """
    benchmark_bytes = BENCHMARK_FILE_MB * 1024 * 1024
    chunk = b"\x00" * (1024 * 1024)  # write in 1 MB chunks

    temp_file = Path(tempfile.mktemp(dir=target_dir, suffix=".benchmark"))
    try:
        start_time = time.perf_counter()
        with temp_file.open("wb") as file_handle:
            for _ in range(BENCHMARK_FILE_MB):
                file_handle.write(chunk)
            file_handle.flush()
        elapsed_seconds = time.perf_counter() - start_time
    finally:
        if temp_file.exists():
            temp_file.unlink()

    write_speed_mbs = BENCHMARK_FILE_MB / elapsed_seconds
    return round(write_speed_mbs, 1)


# =============================================================================
# Storage info
# =============================================================================

def get_free_space_gb(path: Path) -> float:
    """Return free disk space at path in GB."""
    free_bytes = shutil.disk_usage(path).free
    return round(free_bytes / (1024 ** 3), 2)


# =============================================================================
# Per-format write rate estimation
# =============================================================================

# Estimated write rates in MB/s per format at reference resolution (1920×1080, 30fps).
# Scaled linearly by pixel count and fps for other modes.
# Source: empirical estimates for IMX477; stationary scene assumed.
_REFERENCE_PIXEL_COUNT = 1920 * 1080
_REFERENCE_FPS         = 30

_FORMAT_WRITE_RATES_MBS = {
    "MJPEG video (.avi)":  45.0,   # q=95; stationary scene
    "TIFF image stack":   185.0,   # uncompressed 16-bit
    "PNG image stack":     18.0,   # lossless compression; CPU-bound
    "H.264 video (.mp4)":   2.5,   # hardware-encoded; stationary scene
}


# Greyscale reduction factor per format.
# Uncompressed formats scale exactly with channel count (1/3). Compressed
# formats gain less because chroma planes compress well anyway.
_GREYSCALE_FACTORS = {
    "MJPEG video (.avi)": 0.40,
    "TIFF image stack":   0.333,
    "PNG image stack":    0.333,
    "H.264 video (.mp4)": 0.65,
}


def estimate_write_rate_mbs(
    format_label: str,
    frame_width: int,
    frame_height: int,
    fps: float,
    channels: int = 3,
) -> float:
    """
    Estimate the sustained write rate in MB/s for the given format,
    resolution, framerate, and colour mode (channels: 1 = greyscale, 3 = colour).
    """
    base_rate   = _FORMAT_WRITE_RATES_MBS.get(format_label, 0.0)
    pixel_scale = (frame_width * frame_height) / _REFERENCE_PIXEL_COUNT
    fps_scale   = fps / _REFERENCE_FPS
    grey_scale  = _GREYSCALE_FACTORS.get(format_label, 0.333) if channels == 1 else 1.0
    return round(base_rate * pixel_scale * fps_scale * grey_scale, 1)


def estimate_file_size_per_minute_gb(
    format_label: str,
    frame_width: int,
    frame_height: int,
    fps: float,
    channels: int = 3,
) -> float:
    """Return estimated file size in GB per minute of recording."""
    write_rate_mbs = estimate_write_rate_mbs(
        format_label, frame_width, frame_height, fps, channels
    )
    gb_per_minute  = (write_rate_mbs * 60) / 1024
    return round(gb_per_minute, 2)


# =============================================================================
# Headroom calculation
# =============================================================================

def compute_headroom(
    format_label: str,
    frame_width: int,
    frame_height: int,
    fps: float,
    write_speed_mbs: float,
    channels: int = 3,
) -> dict:
    """
    Compute write budget headroom for one format/resolution/fps/colour combination.

    Returns a dict with:
      write_rate_mbs      — estimated write demand
      budget_used_frac    — fraction of usable write budget consumed (0–1+)
      headroom_pct        — usable budget remaining as a percentage
      colour              — "green" | "amber" | "red"
    """
    write_rate_mbs   = estimate_write_rate_mbs(
        format_label, frame_width, frame_height, fps, channels
    )
    usable_speed_mbs = write_speed_mbs * BENCHMARK_SAFETY_MARGIN
    budget_used_frac = write_rate_mbs / usable_speed_mbs if usable_speed_mbs > 0 else 1.0

    headroom_pct = max(0.0, round((1.0 - budget_used_frac) * 100, 1))

    if budget_used_frac <= HEADROOM_GREEN_MAX:
        colour = "green"
    elif budget_used_frac <= HEADROOM_AMBER_MAX:
        colour = "amber"
    else:
        colour = "red"

    return {
        "write_rate_mbs":   write_rate_mbs,
        "budget_used_frac": round(budget_used_frac, 3),
        "headroom_pct":     headroom_pct,
        "colour":           colour,
    }


def compute_max_record_time_s(
    format_label: str,
    frame_width: int,
    frame_height: int,
    fps: float,
    free_space_gb: float,
    channels: int = 3,
) -> float | None:
    """
    Return how many seconds of recording fit in the available free space.
    Returns None if the format has no measurable write rate.
    """
    write_rate_mbs = estimate_write_rate_mbs(
        format_label, frame_width, frame_height, fps, channels
    )
    if write_rate_mbs <= 0:
        return None
    free_space_mbs = free_space_gb * 1024
    return round(free_space_mbs / write_rate_mbs, 0)
