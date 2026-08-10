"""
constants.py
============
App-wide constants and default configuration values.
All tuneable values live here or in config_app.yaml — never hardcoded elsewhere.
"""

APP_NAME    = "RPi Recorder"
APP_VERSION = "0.1.0"

# ── Default paths ──────────────────────────────────────────────────────────────
DEFAULT_SAVE_DIR      = "/home/pi/Projects"
DEFAULT_CONFIG_PATH   = "config_app.yaml"

# ── Preview ────────────────────────────────────────────────────────────────────
PREVIEW_FPS           = 10          # max fps for the live preview stream
PREVIEW_WIDTH         = 960         # preview widget width in pixels
PREVIEW_HEIGHT        = 540         # preview widget height in pixels

# ── Write-speed benchmark ──────────────────────────────────────────────────────
BENCHMARK_FILE_MB     = 400         # size of temp file written during speed test
BENCHMARK_SAFETY_MARGIN = 0.85      # fraction of write speed treated as usable budget

# ── Headroom colour thresholds (fraction of write budget used) ─────────────────
HEADROOM_GREEN_MAX    = 0.70        # below 70% used → green
HEADROOM_AMBER_MAX    = 0.90        # 70–90% used    → amber
                                    # above 90% used → red

# ── Sensor mode filtering ──────────────────────────────────────────────────────
# Tracking never benefits from more than 8 bits per channel, and higher bit
# depths cost framerate and storage. Set to None to expose all bit depths.
ALLOWED_BIT_DEPTHS    = [8]

# ── Colour modes ───────────────────────────────────────────────────────────────
# Greyscale takes only the Y (luma) plane of the YUV stream: 1 byte per pixel
# instead of 3, with no loss of information relevant to tracking.
COLOUR_MODES = [
    ("Greyscale", 1),   # (display_label, channels)
    ("Colour",    3),
]
DEFAULT_COLOUR_MODE   = "Greyscale"

# ── Metadata defaults ──────────────────────────────────────────────────────────
METADATA_DEFAULTS = {
    "experimenter": "NA",
    "experiment":   "NA",
    "treatment":    "NA",
    "trial":        "NA",
}

# ── Supported output formats ───────────────────────────────────────────────────
# Each entry: (display_label, file_extension, description_for_tooltip)
OUTPUT_FORMATS = [
    (
        "MJPEG video (.avi)",
        ".avi",
        "Recommended for tracking. Each frame is compressed independently — "
        "no inter-frame artefacts. Larger files than H.264 but safe for "
        "centroid-based tracking algorithms.",
    ),
    (
        "TIFF image stack",
        ".tiff",
        "Highest quality. Uncompressed, frame-perfect. Best for morphology or "
        "when storage is not a constraint. Write speed limits usable fps.",
    ),
    (
        "PNG image stack",
        ".png",
        "Lossless compression. Good quality at ~10× smaller than TIFF. "
        "PNG encoding is slow — expect frame drops above ~15 fps.",
    ),
    (
        "H.264 video (.mp4)",
        ".mp4",
        "⚠ Use with caution for tracking. Inter-frame compression can smear "
        "fast-moving animals and introduce block artefacts. Smallest file size.",
    ),
]
