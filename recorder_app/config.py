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

from pathlib import Path
import yaml

from constants import DEFAULT_CONFIG_PATH, METADATA_DEFAULTS


# =============================================================================
# App config (hardware calibration + app defaults)
# =============================================================================

def load_app_config(config_file: Path = Path(DEFAULT_CONFIG_PATH)) -> dict:
    """
    Load config_app.yaml. If the file does not exist, return built-in defaults
    so the app can run on first launch before calibration.
    """
    if config_file.exists():
        with config_file.open("r") as file_handle:
            loaded_config = yaml.safe_load(file_handle) or {}
    else:
        loaded_config = {}

    # Merge with defaults so missing keys are always present
    default_config = _default_app_config()
    return _deep_merge(default_config, loaded_config)


def save_app_config(config: dict, config_file: Path = Path(DEFAULT_CONFIG_PATH)) -> None:
    """Persist the app config to disk."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with config_file.open("w") as file_handle:
        yaml.dump(config, file_handle, default_flow_style=False, sort_keys=False)


def _default_app_config() -> dict:
    return {
        "hardware": {
            "sd_write_speed_mbs": None,       # populated after first benchmark
            "sd_write_speed_measured_date": None,
        },
        "app": {
            "save_dir":     "/home/pi/Projects",
            "show_preview": True,
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
    profile_file.parent.mkdir(parents=True, exist_ok=True)
    with profile_file.open("w") as file_handle:
        yaml.dump(profile, file_handle, default_flow_style=False, sort_keys=False)


def default_profile() -> dict:
    """Return a profile dict populated with sensible defaults."""
    return {
        "recording": {
            "save_dir":        "/home/pi/Projects",
            "output_format":   "MJPEG video (.avi)",
            "duration_s":      None,          # None = record until stopped
            "base_name":       "recording",
            "folder_name":     "images",      # used for image stack mode only
        },
        "camera": {
            "sensor_mode":     None,          # None = first available mode
            "fps":             None,          # None = use sensor mode maximum
            "colour_mode":     "Greyscale",   # "Greyscale" or "Colour"
        },
        "metadata": {**METADATA_DEFAULTS, "px_per_cm": None},
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
