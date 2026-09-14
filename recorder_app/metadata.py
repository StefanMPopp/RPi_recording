"""
metadata.py
===========
Builds and writes the per-recording metadata sidecar file.

One YAML file is written per recording, containing everything needed to
interpret the video or image stack later without reference to the app:
experiment context, camera settings, spatial scale, and what actually
happened during capture (duration, frame counts, drops).

Location:
  Video:       {save_dir}/{file_name}_metadata.yaml
  Image stack: {save_dir}/{file_name}/metadata.yaml
"""

from __future__ import annotations

from pathlib import Path

import yaml

from constants import APP_VERSION


# =============================================================================
# Build
# =============================================================================

def build_metadata(settings, capture_summary: dict) -> dict:
    """
    Assemble the full metadata dict from the recording settings and the
    summary returned by RecordingSession.stop().

    Sections:
      experiment  — who/what/which treatment/which trial
      camera      — resolution, framerate, colour mode
      scale       — px per cm, however it was specified
      output      — format and file layout
      capture     — what actually happened (times, frame counts, drops)
      software    — app version, for reproducibility
    """
    metadata_dict = settings.metadata or {}

    return {
        "experiment": {
            "experimenter": metadata_dict.get("experimenter", "NA"),
            "experiment":   metadata_dict.get("experiment",   "NA"),
            "ant_id":       metadata_dict.get("ant_id",       "NA"),
            # Treatments are user-defined name/value pairs, any number of them
            "treatments":   metadata_dict.get("treatments", {}) or {},
            "trial":        metadata_dict.get("trial",        "NA"),
        },
        "camera": {
            "frame_width_px":  settings.frame_width,
            "frame_height_px": settings.frame_height,
            "requested_fps":   settings.fps,
            "colour_mode":     "greyscale" if settings.channels == 1 else "colour",
            "channels":        settings.channels,
            # Fraction of the sensor's full width this mode reads. Modes with
            # the same pixel count can have different fields of view, so this
            # is needed to interpret the spatial scale correctly.
            "fov_fraction_width": round(settings.fov_fraction, 4),
        },
        "scale": {
            "px_per_cm":       metadata_dict.get("px_per_cm"),
            "frame_width_cm":  metadata_dict.get("frame_width_cm"),
            "entered_as":      metadata_dict.get("scale_entered_as"),
        },
        "output": {
            "format":      settings.format_label,
            "file_name":   settings.file_name,
            # The order metadata fields were in when the name was built —
            # lets a reader reconstruct which part of the name is which.
            "field_order": metadata_dict.get("field_order", []),
            "is_image_stack": settings.is_image_stack,
            "path":        str(settings.output_dir if settings.is_image_stack
                               else settings.video_file),
        },
        "capture": {
            "start_datetime":       capture_summary.get("start_datetime"),
            "requested_duration_s": settings.duration_s,
            "actual_duration_s":    capture_summary.get("actual_duration_s"),
            "frames_written":       capture_summary.get("frames_written"),
            # Two distinct failure modes, kept separate because they have
            # different causes and different consequences for the data:
            #   dropped — captured but not written (disk too slow)
            #   missed  — never captured (camera too slow for the rate)
            "frames_dropped":       capture_summary.get("frames_dropped"),
            "frames_missed":        capture_summary.get("frames_missed"),
            "drop_rate_pct":        capture_summary.get("drop_rate_pct"),
            "miss_rate_pct":        capture_summary.get("miss_rate_pct"),
            # requested_fps is what the video container header claims;
            # effective_fps is what was actually achieved. When they differ,
            # frame_times_file is authoritative for any timing analysis.
            "requested_fps":        capture_summary.get("requested_fps"),
            "effective_fps":        capture_summary.get("effective_fps"),
            "fps_shortfall_pct":    capture_summary.get("fps_shortfall_pct"),
            "frame_times_file":     capture_summary.get("frame_times_file"),
            "error":                capture_summary.get("error"),
        },
        "software": {
            "app_version": APP_VERSION,
        },
    }


# =============================================================================
# Write
# =============================================================================

def write_metadata(metadata: dict, metadata_file: Path) -> None:
    """Write the metadata dict to a YAML file, creating parent dirs as needed."""
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    with metadata_file.open("w") as file_handle:
        yaml.dump(
            metadata,
            file_handle,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
