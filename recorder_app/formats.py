"""
formats.py
==========
The output formats the recorder can write.

Each format has a stable `key`, which is what profiles and the code refer to,
and a `label`, which is only for display. Labels can be reworded freely;
keys must not change, or saved profiles stop matching.

Adding a format:
  1. add an OutputFormat here and list it in OUTPUT_FORMATS
  2. give it a writer in record.make_writer (and encoder flags if it needs any)
  3. give it an encoder_signature in record.py if its encoder has settings
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputFormat:
    key:            str     # stable identifier, stored in profiles
    label:          str     # shown in the UI and written to metadata
    extension:      str     # file extension, including the dot
    is_image_stack: bool    # one file per frame, in a folder
    description:    str     # tooltip text


MJPEG = OutputFormat(
    key            = "mjpeg",
    label          = "MJPEG video (.avi)",
    extension      = ".avi",
    is_image_stack = False,
    description    = "Recommended for tracking. Each frame is compressed independently — "
                     "no inter-frame artifacts. Larger files than H.264 but safe for "
                     "centroid-based tracking algorithms.",
)

TIFF = OutputFormat(
    key            = "tiff",
    label          = "TIFF image stack",
    extension      = ".tiff",
    is_image_stack = True,
    description    = "Lossless and frame-perfect. Uncompressed by default; see "
                     "TIFF_COMPRESSION in constants.py to compress it.",
)

PNG = OutputFormat(
    key            = "png",
    label          = "PNG image stack",
    extension      = ".png",
    is_image_stack = True,
    description    = "Lossless. Stored without compression by default, which is fast "
                     "to write but about as large as TIFF; see PNG_MODE in "
                     "constants.py for compressed PNG.",
)

H264 = OutputFormat(
    key            = "h264",
    label          = "H.264 video (.mp4)",
    extension      = ".mp4",
    is_image_stack = False,
    description    = "⚠ Use with caution for tracking. Inter-frame compression can smear "
                     "fast-moving animals and introduce block artifacts. Smallest file size.",
)

OUTPUT_FORMATS: list[OutputFormat] = [MJPEG, TIFF, PNG, H264]
DEFAULT_FORMAT = MJPEG


def find_format(value: str | None) -> OutputFormat | None:
    """
    Look up a format by key, or by label.

    Labels are accepted because profiles saved before keys existed store the
    label; without this, loading one would silently ignore its format.
    """
    for output_format in OUTPUT_FORMATS:
        if value in (output_format.key, output_format.label):
            return output_format
    return None
