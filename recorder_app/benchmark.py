"""
benchmark.py
============
SD card write speed and free space.

Write speed is measured once per card and stored in config_app.yaml. It caps
the frame rate of formats whose frames are large (see
record.measure_format_throughput and record.capacity_for).
"""

import shutil
import tempfile
import time
from pathlib import Path

from constants import BENCHMARK_FILE_MB


# =============================================================================
# Write speed benchmark
# =============================================================================

def measure_write_speed_mbs(target_dir: Path) -> float:
    """
    Measure how fast the card at target_dir can sustain writes, in MB/s.

    The data is forced onto the card with fsync INSIDE the timed region. Without
    that, the operating system accepts the writes into RAM and reports them
    done long before they reach the card — which is how an earlier version of
    this test reported 90 MB/s on a Pi 4, whose SD slot cannot exceed roughly
    40-50 MB/s. Recordings run for minutes, far longer than any RAM cache can
    absorb, so the card's real speed is the one that matters.

    The temp file is deleted immediately after measurement.
    """
    import os
    chunk = os.urandom(4 * 1024 * 1024)            # incompressible, 4 MB
    chunk_count = (BENCHMARK_FILE_MB * 1024 * 1024) // len(chunk)
    written_bytes = chunk_count * len(chunk)

    temp_file = Path(tempfile.mktemp(dir=target_dir, suffix=".benchmark"))
    try:
        start_time = time.perf_counter()
        with temp_file.open("wb") as file_handle:
            for _ in range(chunk_count):
                file_handle.write(chunk)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        elapsed_seconds = time.perf_counter() - start_time
    finally:
        if temp_file.exists():
            temp_file.unlink()

    return round(written_bytes / (1024 * 1024) / elapsed_seconds, 1)


# =============================================================================
# Storage info
# =============================================================================

def get_free_space_gb(path: Path) -> float:
    """Return free disk space at path in GB."""
    free_bytes = shutil.disk_usage(path).free
    return round(free_bytes / (1024 ** 3), 2)
