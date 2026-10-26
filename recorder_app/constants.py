"""
constants.py
============
App-wide constants and default configuration values.
All tuneable values live here or in config_app.yaml — never hardcoded elsewhere.
"""

from pathlib import Path

APP_NAME    = "RPi Recorder"
APP_VERSION = "1.0.0"

# ── Default paths ──────────────────────────────────────────────────────────────
# Derived from the running user's home directory rather than hardcoded, because
# the username differs between machines (the Raspberry Pi Imager lets you choose
# it, and 'pi' is no longer the default). A hardcoded path fails on any Pi whose
# user is named differently.
DEFAULT_SAVE_DIR      = str(Path.home() / "Projects")
# The app config lives at the repository root, found from this file's location
# rather than the current directory, so it is the same file however the app
# is started (desktop launcher, or `python3 main.py` from any directory).
DEFAULT_CONFIG_PATH   = str(Path(__file__).resolve().parent.parent / "config_app.yaml")

# ── Preview ────────────────────────────────────────────────────────────────────
PREVIEW_FPS           = 10          # max fps for the live preview stream
PREVIEW_WIDTH         = 960         # preview stream width in pixels;
                                    # height is derived from the sensor mode's
                                    # aspect ratio so the full frame is shown

# ── Write-speed benchmark ──────────────────────────────────────────────────────
BENCHMARK_FILE_MB     = 400         # size of temp file written during speed test
BENCHMARK_SAFETY_MARGIN = 0.85      # fraction of write speed treated as usable budget

# ── Sensor mode filtering ──────────────────────────────────────────────────────
# Tracking never benefits from more than 8 bits per channel, and higher bit
# depths cost framerate and storage. Set to None to expose all bit depths.
ALLOWED_BIT_DEPTHS    = [8]

# ── Color modes ───────────────────────────────────────────────────────────────
# Grayscale takes only the Y (luma) plane of the YUV stream: 1 byte per pixel
# instead of 3, with no loss of information relevant to tracking.
COLOR_MODES = [
    ("Grayscale", 1),   # (display_label, channels)
    ("Color",    3),
]
DEFAULT_COLOR_MODE   = "Grayscale"

# ── Hardware H.264 ────────────────────────────────────────────────────────────
# The Pi 4 has a dedicated H.264 encoder, used automatically when it passes a
# streaming test at the chosen resolution. It is restricted to 1080p and below,
# and on some systems fails once frames actually stream even though the test
# passes — in which case the app falls back to software automatically and
# remembers not to retry.
#
# Set False to never attempt it, which avoids a few seconds of probing and any
# risk of a mid-recording failure. Software H.264 is slower than MJPEG at high
# resolution, so at 4K this costs nothing.
ENABLE_HARDWARE_H264 = True

# ── Image stack encoding ──────────────────────────────────────────────────────
# Defaults favor FRAME RATE over file size: both stack formats are written
# uncompressed. If the measurement table reports the SD card as the limit for
# a format, switching it to a compressed option below may raise its rate.
#
# Lossless stacks trade CPU time against bytes written, and which side limits
# a recording depends on the machine. At 4K grayscale a frame is 12.3 MB raw,
# so a card sustaining ~90 MB/s caps UNCOMPRESSED stacks near 7 fps no matter
# how fast encoding is, while compressing costs CPU the Pi has little of.
# Neither choice wins everywhere, so both are exposed. Measure with
# Settings -> Measure maximum fps after changing either.
#
# Figures below: 4056x3040 grayscale, desktop CPU, so ratios matter, not the
# absolute times. Real footage with less sensor noise compresses better.
#
#   PNG default (OpenCV, no flags)   ~135 ms   8.2 MB   <- PNG_MODE = "default"
#   PNG stored, no filter             ~30 ms  12.4 MB   <- PNG_MODE = "store"
#   TIFF LZW                         ~207 ms  10.5 MB   <- TIFF_COMPRESSION = "lzw"
#   TIFF deflate                     ~184 ms   8.4 MB   <- "deflate"
#   TIFF uncompressed                 ~20 ms  12.3 MB   <- "none"

# "default": OpenCV's own PNG settings, which are tuned for speed (fast filter,
#            fast strategy). Compressed, about 8 MB per 4K grayscale frame.
# "store":   no compression and no filtering. Still a valid lossless PNG that
#            every tool opens, ~4x faster to write, ~50% larger. Needs a recent
#            OpenCV (exposes IMWRITE_PNG_FILTER); older builds fall back to
#            "default" rather than doing something slower.
PNG_MODE = "store"

# PNG_COMPRESSION_LEVEL: leave None. Setting a level on its own is SLOWER, not
# faster: measured 351 ms vs 135 ms, because it drops the fast filter and
# strategy OpenCV otherwise picks. Only useful together with explicit filter
# settings, which this app does not expose.
PNG_COMPRESSION_LEVEL = None

# "none" writes uncompressed TIFFs, about 10x faster to encode than "lzw",
# which is OpenCV's own default.
TIFF_COMPRESSION = "none"     # "none" | "lzw" | "deflate"

# Frames that may sit buffered between capture and writing.
#
# MUST stay below camera._BUFFER_POOL_SIZE. Capture hands out frame buffers
# from a rotating pool, so a queue deeper than that pool would let a buffer be
# reused while an earlier frame still waiting in the queue points at it —
# silently corrupting footage rather than failing visibly.
#
# A shallower queue also means less RAM held in flight (a 4K frame is ~12 MB)
# and quicker, more honest drop reporting when the disk falls behind.
FRAME_QUEUE_SIZE = 8

# Threads used to encode image-stack frames. The Pi 4 has four cores and the
# capture thread needs one, so three leaves the system responsive. Raising this
# to 4 can help when encoding dominates, at the cost of preview smoothness.
IMAGE_STACK_WORKERS = 3

# ── Metadata defaults ──────────────────────────────────────────────────────────
# Treatments are not listed here — they are user-defined name/value pairs.
METADATA_DEFAULTS = {
    "experimenter": "NA",
    "experiment":   "NA",
    "ant_id":       "NA",
    "trial":        "NA",
}

# ── Metadata fields that feed the automatic file name ─────────────────────────
# (key, display label). Experimenter is deliberately absent: it identifies the
# person, not the recording, so including it would make names longer without
# making them more distinguishing.
FILENAME_FIELDS = [
    ("experiment", "Experiment"),
    ("ant_id",     "Ant ID"),
    ("trial",      "Trial"),
]

# Default order of file-name components. Treatments are appended after these
# unless the user drags them elsewhere. Change this to alter the default for
# new installations; existing profiles keep whatever order they saved.
DEFAULT_FIELD_ORDER = ["experiment", "ant_id", "trial"]
