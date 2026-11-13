#!/usr/bin/env bash
# =============================================================================
# install.sh — install or update the recorder on this Pi, without Ansible
# =============================================================================
#
# For a Pi set up by hand (keyboard and monitor), not managed from the dev Pi.
# Run as the normal user, not with sudo; it asks for the password when needed.
#
# First install, on a fresh Raspberry Pi OS:
#
#     curl -sSL https://raw.githubusercontent.com/StefanMPopp/RPi_recording/main/install.sh | bash
#
# Update, any time afterwards (the app must be closed):
#
#     ~/RPi_recording/install.sh
#
# The app runs the same update from Settings -> Update app, with --from-app:
# then the app may stay open (it restarts itself afterwards), and sudo never
# asks for a password, since there is no terminal to type it into.
#
# Safe to re-run: anything already in place is left as it is. Local edits to
# the code stop the script rather than being discarded.
#
# The system package list is read from ansible/group_vars/pis.yml, the same
# list bootstrap.yml installs on fleet Pis, so the two never drift apart.
#
# Everything runs from main(), called on the last line, so bash has read the
# whole file before git pull can replace it.

set -euo pipefail

REPO_URL="https://github.com/StefanMPopp/RPi_recording.git"
BRANCH="main"
REPO_DIR="$HOME/RPi_recording"
PROJECTS_DIR="$HOME/Projects"
LAUNCHER="$HOME/Desktop/RPi Recorder.desktop"
FROM_APP=false
SUDO=(sudo)

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

preflight() {
    [[ $EUID -ne 0 ]] || fail "run this as your normal user, not with sudo."

    # The app updates itself while open and restarts once this has finished.
    ! $FROM_APP || return 0

    # Matches a python process running main.py, not this script or a shell.
    if pgrep -f "^(/usr/bin/)?python3? .*recorder_app/main\.py" >/dev/null; then
        fail "the recorder app is running. Close it (finish any recording first), then run this again."
    fi
}

ensure_git() {
    if ! command -v git >/dev/null; then
        step "Installing git"
        "${SUDO[@]}" apt-get update
        "${SUDO[@]}" apt-get install -y git
    fi
}

get_code() {
    if [[ ! -d "$REPO_DIR/.git" ]]; then
        step "Downloading the recorder to $REPO_DIR"
        [[ ! -e "$REPO_DIR" ]] || fail "$REPO_DIR exists but is not a git checkout. Move it aside and run this again."
        git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
        return
    fi

    step "Updating the recorder in $REPO_DIR"
    cd "$REPO_DIR"
    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
        git status --short --untracked-files=no
        fail "files in $REPO_DIR were edited on this Pi (listed above), so the update stopped.
Code should not be edited on a recording Pi. To discard the edits and update:
    cd $REPO_DIR && git reset --hard && $REPO_DIR/install.sh"
    fi
    local before
    before=$(git log -1 --oneline)
    # Leaves a rollback (detached checkout of an older version) for main again.
    git checkout --quiet "$BRANCH"
    git pull --ff-only
    local after
    after=$(git log -1 --oneline)
    if [[ "$before" == "$after" ]]; then
        echo "Already up to date: $after"
    else
        echo "Updated from: $before"
        echo "          to: $after"
    fi
}

system_packages() {
    # The indented "- name" lines under system_packages:, comments skipped.
    awk '
        /^system_packages:/ { inlist = 1; next }
        !inlist { next }
        /^[[:space:]]*#/ || !NF { next }
        /^[[:space:]]+-[[:space:]]/ {
            sub(/^[[:space:]]+-[[:space:]]+/, ""); sub(/[[:space:]]*#.*/, "")
            print; next
        }
        { exit }
    ' "$REPO_DIR/ansible/group_vars/pis.yml"
}

install_packages() {
    local packages
    mapfile -t packages < <(system_packages)
    [[ ${#packages[@]} -gt 0 ]] || fail "no system packages found in ansible/group_vars/pis.yml."

    local missing=()
    for p in "${packages[@]}"; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || missing+=("$p")
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        step "System packages already installed"
    else
        step "Installing system packages: ${missing[*]}"
        if ! "${SUDO[@]}" true 2>/dev/null; then
            fail "this update needs new system packages (${missing[*]}), which need the
password. Close the app and run in a terminal:
    $REPO_DIR/install.sh"
        fi
        "${SUDO[@]}" apt-get update
        "${SUDO[@]}" apt-get install -y "${missing[@]}"
    fi

    step "Installing Python packages"
    pip install --quiet -r "$REPO_DIR/recorder_app/requirements.txt" --break-system-packages
}

install_launcher() {
    step "Creating the recordings folder and desktop icon"
    mkdir -p "$PROJECTS_DIR" "$(dirname "$LAUNCHER")"
    cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=RPi Recorder
Comment=Record animal behavior video
Exec=python3 $REPO_DIR/recorder_app/main.py
Path=$REPO_DIR
Icon=camera-video
Terminal=false
Categories=Science;
EOF
    chmod +x "$LAUNCHER"
}

check_camera() {
    # rpicam-hello on current Raspberry Pi OS, libcamera-hello on older releases
    local tool cameras=""
    tool=$(command -v rpicam-hello || command -v libcamera-hello || true)
    [[ -z "$tool" ]] || cameras=$("$tool" --list-cameras 2>&1 || true)
    if grep -qi imx477 <<<"$cameras"; then
        echo "Camera:   IMX477 detected"
    else
        echo "Camera:   NOT DETECTED - check the ribbon cable at both ends"
    fi
}

main() {
    case "${1:-}" in
        "") ;;
        --from-app) FROM_APP=true; SUDO=(sudo -n) ;;
        *) fail "unknown option: $1" ;;
    esac

    preflight
    ensure_git
    get_code
    install_packages
    install_launcher

    step "Done"
    echo "Version:  $(git -C "$REPO_DIR" log -1 --oneline)"
    # The open app holds the camera, so it cannot be listed from here.
    ! $FROM_APP || return 0
    check_camera
    echo
    echo "Start the recorder with the 'RPi Recorder' icon on the desktop."
    echo "On a new Pi or SD card, run Settings -> Recalibrate write speed once."
}

main "$@"
