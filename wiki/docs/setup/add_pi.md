# Add a new Pi

From a blank SD card to a working rig. Budget about 30 minutes, most of it
waiting for downloads.

Two parts: **manual preparation** needing physical access, then
**bootstrapping**, which is automatic.

---

## Part 1 — Manual preparation

### 1.1 Flash the OS

1. Open Raspberry Pi Imager
2. OS: **Raspberry Pi OS (64-bit)** — the desktop version, because the recorder
   app is graphical
3. Advanced options (gear icon):
     - Hostname: `pi1`, `pi2`, … — unique per rig
     - **Enable SSH**
     - Same username and password as the other rigs, for consistency
     - Wi-Fi if not using ethernet
4. Flash, insert, boot

### 1.2 Enable the camera

The HQ camera normally works out of the box on current Raspberry Pi OS. Confirm:

```bash
libcamera-hello --list-cameras
```

If the IMX477 is not listed, check the ribbon cable at both ends before
anything else.

### 1.3 Find the Pi on the network

Ansible needs a stable address for each Pi. There are two ways to get one —
use whichever works on your network.

=== "Hostname (recommended)"
    Raspberry Pi OS runs mDNS by default, so a Pi is reachable at
    `<hostname>.local` regardless of what address DHCP hands it — no router
    access needed, and it keeps working even if the address changes after a
    reboot. This is the more reliable option on institutional networks, which
    often don't allow reserving addresses, and on a direct switch connection
    with no router at all.

    ```bash
    ping -c 2 pi1.local
    ```

    If that answers, use `pi1.local` as the address everywhere below.

=== "Static IP"
    If you have router access and prefer a fixed address:

    1. Let the Pi connect and wait a minute
    2. Open your router's admin panel
    3. Find the Pi by its hostname
    4. Reserve an address for it

    Suggested scheme:

    | Machine | Hostname | IP |
    |---|---|---|
    | Dev Pi | `devpi` | `192.168.50.100` |
    | Rig 1 | `pi1` | `192.168.50.101` |
    | Rig 2 | `pi2` | `192.168.50.102` |
    | … | … | … |

The rest of this page uses `pi1.local` — substitute a static IP if that's
what you're using instead.

### 1.4 Copy the SSH key

From the **dev Pi**, with the new rig's address:

```bash
ssh-copy-id -i ~/.ssh/rig_recording.pub pi@pi1.local
```

You will be asked for the rig's password once. Verify:

```bash
ssh -i ~/.ssh/rig_recording pi@pi1.local
```

You should land in a terminal on the new Pi. Type `exit` to return.

### 1.5 Add it to the inventory

On the dev Pi, edit `~/RPi_recording/ansible/inventory.ini`:

```ini
[pis]
pi1 ansible_host=pi1.local
pi2 ansible_host=pi2.local    # ← new line

[pis:vars]
ansible_user=pi
ansible_ssh_private_key_file=~/.ssh/rig_recording
```

Then commit it — the inventory is part of the project record:

```bash
cd ~/RPi_recording
git add ansible/inventory.ini
git commit -m "add pi2 to inventory"
git push
```

### 1.6 Create its unit config

Each rig has hardware-specific values that must not be shared:

```bash
cp ansible/host_vars/template.yml ansible/host_vars/pi2.yml
nano ansible/host_vars/pi2.yml
```

```yaml
unit_id: pi2
arena_width_cm: 30
arena_height_cm: 20
notes: "bench 2, north window"
```

!!! note "These files are not committed"
    `ansible/host_vars/*.yml` is in `.gitignore` because the values differ per
    machine. Only `template.yml` is tracked. Keep a backup of these files
    somewhere outside the repo — see the
    [handover checklist](../reference/handover.md).

---

## Part 2 — Bootstrap

Installs everything the rig needs. Run from the dev Pi:

```bash
cd ~/RPi_recording/ansible
ansible-playbook -i inventory.ini bootstrap.yml --limit pi2
```

Drop `--limit pi2` to bootstrap every Pi in the inventory. The playbook is
**idempotent** — running it on an already-configured Pi is safe and skips
whatever is already correct.

It will:

1. Install system packages — `git`, `python3-pyqt6`, `python3-picamera2`,
   `python3-opencv`, `ffmpeg`
2. Clone the repository to the Pi
3. Install the Python dependencies
4. Deploy the unit config from `host_vars/`

Expect 2–5 minutes on a fresh Pi, mostly downloading.

---

## Part 3 — Verify

```bash
ansible pis -i inventory.ini -m ping
```

Every Pi should answer `pong`.

Then on the rig itself, with its monitor attached:

```bash
cd ~/RPi_recording
python3 recorder_app/main.py
```

Check:

- [ ] The app opens
- [ ] The preview shows a live image
- [ ] The sensor mode dropdown lists the IMX477 modes
- [ ] **Settings → Recalibrate write speed** completes and gives a plausible
      figure (20–90 MB/s for a U30 card)
- [ ] A 10-second test recording produces a file and a metadata file, with no
      dropped frames

The write speed calibration is **per Pi** — it measures that particular SD card
and is stored in `config_app.yaml`, which is not shared between machines.

---

## Adding several Pis at once

Do Part 1 for all of them, then bootstrap in one pass:

```bash
ansible-playbook -i inventory.ini bootstrap.yml
```

Ansible works on all hosts in parallel, so ten Pis take about as long as one.

---

## If something fails

### ssh-copy-id hangs after "Source of key(s) to be installed"

The key file was found; nothing at that address is answering. The command is
waiting for a TCP connection that will eventually time out.

If `pi1.local` didn't resolve in step 1.3 either, work through these in order:

**Is it actually on the network?** A Pi flashed without Wi-Fi credentials boots
normally but never joins. Attach a monitor and check, or use ethernet.

**Try the default hostname**, in case the custom one from Imager didn't take:

```bash
ping -c 2 raspberrypi.local
```

**Fall back to an IP scan.** Confirm your subnet first —
`192.168.0.x` and `10.0.0.x` are as common as `192.168.50.x`:

```bash
ip route | grep default
```

Then scan it. Raspberry Pis are identifiable by their MAC vendor:

```bash
sudo apt install -y nmap
nmap -sn 192.168.50.0/24
```

**Is SSH enabled?** If "Enable SSH" was not ticked in Imager, the Pi is
reachable by ping but refuses connections — that gives `Connection refused`
rather than a hang.

### ssh-copy-id asks for a password and rejects it

The username is wrong. It is the one set in Imager when that Pi was flashed,
not the one on the dev Pi — though keeping them the same across all machines
avoids exactly this confusion. `ansible_user` in `inventory.ini` assumes they
match.

### Missing sudo password

`bootstrap.yml` needs `sudo` on the rig for installing packages, and Ansible
doesn't have a password for it. Set up passwordless sudo once per rig — this
matches how Raspberry Pi OS's default user is normally configured, so it's
likely something changed rather than a step that was always needed:

```bash
ssh pi@pi1.local
echo "pi ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/010_pi-nopasswd
exit
```

Or, without changing anything on the rig, supply the password each run:

```bash
ansible-playbook -i inventory.ini bootstrap.yml --limit pi1 --ask-become-pass
```

### Playbook failures

Ansible names the failing task and host. Common causes:

| Symptom | Cause | Fix |
|---|---|---|
| `UNREACHABLE` | Pi off, wrong IP, or key not copied | Repeat 1.3 and 1.4 |
| `Permission denied` | SSH key missing, or wrong `ansible_user` | Repeat 1.4; check the username |
| `Missing sudo password` | The rig's user needs a password for `sudo` | Set up passwordless sudo for that user, or re-run with `--ask-become-pass` |
| `Failed to update apt cache` | Usually a network problem, sometimes a captive portal | SSH in and run `sudo apt update` directly to see the real error |
| Git clone `Permission denied (publickey)` on the **rig** | The read-only deploy key hasn't been generated or added to GitHub yet | See [dev Pi setup, step 5](dev_pi.md#5-generate-a-read-only-key-for-the-recording-rigs) — one-time, then automatic for every rig |
| Repo clone fails on the **dev Pi** | Dev Pi's own write-access deploy key missing | See [dev Pi setup, step 4](dev_pi.md#4-give-github-the-public-key) |

Fix and re-run — completed steps are skipped. To retry just the GitHub key
step without repeating everything else:

```bash
ansible-playbook -i inventory.ini bootstrap.yml --limit pi1 --tags github
```
