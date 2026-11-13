# Install on a single Pi

Sets up and updates the recorder on one Pi, working directly at that Pi with a
keyboard, mouse and monitor. You don't need a dev Pi, Ansible, SSH keys or
another computer, only internet access. One command installs everything, and
the same command updates it later.

Use this page for a one-off rig, a rig in another lab, or a quick test setup.
If the Pi belongs to the managed fleet, use [Add a new Pi](add_pi.md) instead.
That way the dev Pi can update it together with the others.

!!! warning "Standalone Pis are not updated by `update.yml`"
    A Pi set up this way is not in the Ansible inventory, so fleet updates
    don't reach it. You have to update it yourself, as described
    [below](#updating). To move it into the fleet later, follow
    [Add a new Pi](add_pi.md) from step 1.3. You don't need to reflash it.

---

## What you need

- A Raspberry Pi 4 with the HQ camera (IMX477) attached
- An SD card, 32 GB or more
- Keyboard, mouse and monitor
- Internet access on the Pi (ethernet or Wi-Fi)
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on any computer,
  to flash the card

---

## 1. Flash the OS

1. Open Raspberry Pi Imager
2. OS: **Raspberry Pi OS (64-bit)**, the desktop version. The recorder app is
   graphical.
3. In the advanced options (gear icon), set:
     - Hostname, e.g. `pi9`
     - Username and password. Use the same ones as the other rigs, so the
       Pi can join the fleet later without trouble.
     - Wi-Fi, if you're not using ethernet
     - Enabling SSH is optional. It isn't needed here, but it lets you add the
       Pi to the fleet later without going back to it.
4. Flash the card, put it in the Pi and boot. The desktop appears after a minute
   or two on first boot.

---

## 2. Install the recorder

Open a terminal (the black icon in the top bar, or ++ctrl+alt+t++) and run:

```bash
curl -sSL https://raw.githubusercontent.com/StefanMPopp/RPi_recording/main/install.sh | bash
```

Enter your password when `sudo` asks for it. Expect a few minutes on a fresh
install, mostly downloading. The script:

1. Downloads the recorder to `~/RPi_recording`. The repository is public, so
   this needs no key or GitHub account.
2. Installs the system packages, using the same list `bootstrap.yml` installs
   on fleet Pis (`ansible/group_vars/pis.yml`)
3. Installs the Python packages from `recorder_app/requirements.txt`
4. Creates `~/Projects`, where recordings are saved, and an **RPi Recorder**
   icon on the desktop
5. Checks for the camera and prints a summary

The summary ends like this:

```
==> Done
Version:  f5511ac Release 1.2.0: snapshot button
Camera:   IMX477 detected
```

If it says `Camera: NOT DETECTED`, power off and reseat the ribbon cable at
both ends. The software is installed either way, so you don't need to run the
script again afterwards.

The first time you double-click the desktop icon, the desktop may ask whether
to run or trust it. Choose **Execute** (or **Trust**), and it won't ask again.

---

## 3. Verify

Start the app with the desktop icon and check:

- [ ] The app opens
- [ ] The preview shows a live image
- [ ] The sensor mode dropdown lists the IMX477 modes
- [ ] **Settings → Recalibrate write speed** completes and gives a plausible
      figure (roughly 20–45 MB/s on a Pi 4's SD slot)
- [ ] A 10-second test recording produces a video file and a metadata file,
      with no dropped frames

The write-speed calibration is stored in `config_app.yaml` on this Pi only.
Updates leave it alone.

---

## Updating

From the app: **Settings → Update app**. With *Check for updates at startup*
switched on (the default), the app also offers each new release when it starts.
Either way it runs the same `install.sh` as below and restarts itself.

If a release needs new system packages and `sudo` asks for a password on this
Pi, the app cannot type it, so it stops and says so. Then update from a
terminal: close the recorder app, and run:

```bash
~/RPi_recording/install.sh
```

The same script installs and updates. On a Pi that is already set up, it pulls
the latest code, installs any system or Python packages a new release needs,
and prints the old and new version:

```
Updated from: d293b73 Release 1.1.0: 8-bit readout, rectangular recording crop
          to: f5511ac Release 1.2.0: snapshot button
```

It refuses to run while the app is open, so a recording can't be interrupted
by accident. Your calibration (`config_app.yaml`) and recordings in
`~/Projects` are never touched.

### "Files were edited on this Pi, so the update stopped"

Someone changed a file in `~/RPi_recording` on this Pi. Code should never be
edited on a recording Pi, because the repository is the source of truth. The
script lists the changed files and stops, so nothing is lost without you
deciding. To discard the edits and update:

```bash
cd ~/RPi_recording && git reset --hard && ~/RPi_recording/install.sh
```

If the edit was a real fix, send it to whoever maintains the code before you
discard it.

### Going back to an earlier version

If a new release causes a problem in the middle of an experiment:

```bash
cd ~/RPi_recording
git log --oneline -10            # find the version you want
git checkout <commit>            # e.g. git checkout d293b73
```

The next run of `install.sh`, or **Settings → Update app**, brings the Pi back
to the latest version. Switch off *Settings → Check for updates at startup* if
the app should not offer that.

---

## Doing it by hand

If the script fails and you want to work through it step by step, these are
the same steps:

??? note "Manual install"
    ```bash
    sudo apt update
    sudo apt install -y git
    git clone https://github.com/StefanMPopp/RPi_recording.git ~/RPi_recording

    # system packages: the list under system_packages: in this file
    sed -n '/^system_packages:/,$p' ~/RPi_recording/ansible/group_vars/pis.yml
    sudo apt install -y <those packages>

    pip install -r ~/RPi_recording/recorder_app/requirements.txt --break-system-packages
    mkdir -p ~/Projects
    ```

    To update by hand: `cd ~/RPi_recording && git pull`, then repeat the `pip`
    line. The desktop icon is optional. You can also start the app from a
    terminal with `cd ~/RPi_recording && python3 recorder_app/main.py`, which
    is also the way to see error messages if it fails to start.
