"""
updater.py
==========
Checks GitHub for a newer release of the app and installs it.

The latest version is the APP_VERSION in constants.py on the main branch,
read over HTTPS from raw.githubusercontent.com: a single request of a few
kilobytes, no login, no git needed. Only a version bump counts as an update,
so commits pushed between releases do not prompt anyone.

Installing runs install.sh --from-app, the same steps as a manual update
from a terminal (git pull, then any new packages), so there is one update
path to maintain. No Qt here; the window runs these off the UI thread.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from constants import APP_NAME, APP_VERSION

REPO_DIR        = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT  = REPO_DIR / "install.sh"
VERSION_URL     = ("https://raw.githubusercontent.com/StefanMPopp/RPi_recording/"
                   "main/recorder_app/constants.py")

CHECK_TIMEOUT_S   = 10
# A git pull is seconds; new apt packages can take several minutes.
INSTALL_TIMEOUT_S = 15 * 60

_VERSION_LINE = re.compile(r'^APP_VERSION\s*=\s*["\']([0-9][0-9.]*)["\']', re.MULTILINE)
_ANSI_CODE    = re.compile(r"\x1b\[[0-9;]*m")


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".") if part)


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def fetch_latest_version() -> str:
    """
    Return the APP_VERSION on GitHub's main branch. Raises OSError when
    GitHub cannot be reached (no network, timeout), ValueError when the file
    holds no version.
    """
    request = urllib.request.Request(VERSION_URL, headers={"User-Agent": APP_NAME})
    with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT_S) as response:
        text = response.read().decode("utf-8", errors="replace")
    match = _VERSION_LINE.search(text)
    if match is None:
        raise ValueError("no APP_VERSION found in the latest constants.py")
    return match.group(1)


def install_update() -> tuple[bool, str]:
    """
    Run install.sh --from-app. Returns (succeeded, output), the output being
    what the script printed, for showing when it fails.
    """
    try:
        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--from-app"],
            cwd=REPO_DIR,
            stdin=subprocess.DEVNULL,       # never wait for typed input
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=INSTALL_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    return result.returncode == 0, _ANSI_CODE.sub("", result.stdout)


def restart_app() -> None:
    """Replace this process with a fresh start of the app, running the new code."""
    main_script = Path(sys.argv[0]).resolve()
    os.execv(sys.executable, [sys.executable, str(main_script), *sys.argv[1:]])
