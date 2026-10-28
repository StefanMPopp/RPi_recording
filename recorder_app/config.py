"""
config.py
=========
Loads, saves, and validates the app config (config_app.yaml) and
per-session profile files. Both use YAML.

Config hierarchy:
  1. config_app.yaml  — hardware calibration, app-level defaults (write speed, etc.)
  2. profile .yaml    — user-saved session parameters (paths, metadata, format)
  3. UI state         — live values in the form; overrides profile on record start
"""

import os
import tempfile
from pathlib import Path

import yaml

from constants import (
    DEFAULT_CONFIG_PATH, DEFAULT_SAVE_DIR, METADATA_DEFAULTS, DEFAULT_FIELD_ORDER,
)
from formats import DEFAULT_FORMAT


# =============================================================================
# App config (hardware calibration + app defaults)
# =============================================================================

def load_app_config(config_file: Path = Path(DEFAULT_CONFIG_PATH)) -> dict:
    """
    Load config_app.yaml. If the file does not exist, return built-in defaults
    so the app can run on first launch before calibration.
    """
    loaded_config = {}
    if config_file.exists():
        try:
            with config_file.open("r") as file_handle:
                loaded_config = yaml.safe_load(file_handle) or {}
        except yaml.YAMLError:
            # Unreadable config: keep it for inspection under another name
            # and start from defaults, rather than refusing to start.
            config_file.replace(config_file.with_name(config_file.name + ".corrupt"))
        if not isinstance(loaded_config, dict):
            loaded_config = {}

    _drop_stale_throughput(loaded_config)

    # Merge with defaults so missing keys are always present
    default_config = _default_app_config()
    return _deep_merge(default_config, loaded_config)


# Color-mode names used by app versions before 1.0, still accepted when
# loading profiles
LEGACY_COLOR_MODES  = {"Greyscale": "Grayscale", "Colour": "Color"}


def _drop_stale_throughput(config: dict) -> None:
    """
    Remove fps measurements whose key does not name the sensor bit depth.

    Those were taken before the app chose the bit depth, when the camera ran
    its slower 12-bit readout, so they understate what it sustains now.
    Current keys contain e.g. "@8bit_" (see record.throughput_cache_key).
    """
    throughput = config.get("throughput")
    if not isinstance(throughput, dict):
        return
    for key in [key for key in throughput if "bit_" not in key]:
        del throughput[key]


def save_app_config(config: dict, config_file: Path = Path(DEFAULT_CONFIG_PATH)) -> None:
    """Persist the app config to disk."""
    write_yaml_atomic(config, config_file)


def _default_app_config() -> dict:
    return {
        "hardware": {
            "sd_write_speed_mbs": None,       # populated after first benchmark
            "sd_write_speed_measured_date": None,
        },
        # Measured maximum sustained fps, keyed by resolution+color+format.
        # Populated by Settings -> Measure maximum fps. Machine-specific, so
        # not committed — though unlike SD write speed, which depends on the
        # individual card, these depend on the Pi model and camera and are
        # broadly consistent across identical rigs.
        "throughput": {},
        "app": {
            "save_dir":     DEFAULT_SAVE_DIR,
            "show_preview": True,
            # File naming: include treatment NAMES alongside values?
            #   False -> foraging_high-dim_3
            #   True  -> foraging_density-high-light-dim_3
            "include_treatment_names": False,
        },
    }


# =============================================================================
# Session profiles
# =============================================================================

def load_profile(profile_file: Path) -> dict:
    """Load a session profile YAML and return its contents as a dict."""
    with profile_file.open("r") as file_handle:
        return yaml.safe_load(file_handle) or {}


def save_profile(profile: dict, profile_file: Path) -> None:
    """Save the current session parameters to a profile YAML file."""
    write_yaml_atomic(profile, profile_file)


def default_profile() -> dict:
    """Return a profile dict populated with sensible defaults."""
    return {
        "recording": {
            "save_dir":        DEFAULT_SAVE_DIR,
            "output_format":   DEFAULT_FORMAT.key,
            "duration_s":      None,          # None = record until stopped
            "base_name":       "recording",
            "auto_file_name":  True,      # build the name from metadata
        },
        "camera": {
            "sensor_mode":     None,          # None = first available mode
            "fps":             None,          # None = use sensor mode maximum
            "color_mode":     "Grayscale",   # "Grayscale" or "Color"
            # Recorded region in full-sensor pixels, [x, y, width, height];
            # None = the whole frame
            "crop":           None,
        },
        "metadata": {
            **METADATA_DEFAULTS,
            "treatments":     {},     # {name: value}, any number
            "field_order":    list(DEFAULT_FIELD_ORDER),
            "px_per_cm":      None,
        },
    }


# =============================================================================
# Helpers
# =============================================================================

def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge override into base.
    Keys in override take precedence; keys only in base are preserved.
    """
    merged = dict(base)
    for key, override_value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge(merged[key], override_value)
        else:
            merged[key] = override_value
    return merged


def write_yaml_atomic(data: dict, target_file: Path) -> None:
    """
    Write YAML so that target_file is always either the old or the new
    version, never a partial one.

    The data goes to a temporary file in the same directory, is flushed to
    the card, and then replaces the target in one rename. Rigs lose power
    without warning, and a config truncated mid-write would stop the app
    from starting.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=target_file.parent, prefix=f".{target_file.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(file_descriptor, "w") as file_handle:
            yaml.dump(data, file_handle, default_flow_style=False,
                      sort_keys=False, allow_unicode=True)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_name, target_file)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
