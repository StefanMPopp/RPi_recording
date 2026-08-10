# Step 2: Add a new Pi

This page covers everything needed to bring a new recording Pi into the fleet — from a
blank SD card to a fully configured rig ready to record.

The process has two parts:

1. **Manual preparation** — flash the Pi, assign it a static IP, and copy the SSH key.
   This requires physical access to the Pi and your router.
2. **Bootstrapping via the Manager app** — installs all software on the Pi automatically.

---

## Part 1 — Manual preparation

### 1.1 Flash the Pi

1. Open Raspberry Pi Imager on any computer.
2. Select **Raspberry Pi OS Lite (64-bit)** — the Lite version has no desktop, which saves
   resources on a Pi that only records video.
3. Select your SD card.
4. Click the **gear icon** and set:
    - Hostname: `pi1` (increment for each new Pi: `pi2`, `pi3` …)
    - Enable SSH: **checked**
    - Username: `pi`
    - Same password as the dev Pi
    - Configure Wi-Fi if not using ethernet
5. Flash and insert the card.

---

### 1.2 Assign a static IP address

A static IP means the Pi always has the same network address. Ansible needs this to find
each Pi reliably.

1. Power on the Pi and let it connect to the network (give it ~60 seconds).
2. Log into your **router's admin panel** (usually at `192.168.1.1` or `192.168.0.1` in a browser).
3. Find the Pi in the connected devices list — it will appear as `pi1` (or the hostname you set).
4. Assign it a reserved/static IP. Suggested scheme:

    | Pi | Hostname | Static IP |
    |---|---|---|
    | Dev Pi | `devpi` | `192.168.1.100` |
    | Pi 1 | `pi1` | `192.168.1.101` |
    | Pi 2 | `pi2` | `192.168.1.102` |
    | … | … | … |

5. Save and restart the router if prompted.

---

### 1.3 Copy the SSH key to the new Pi

Run this from the dev Pi terminal, replacing the IP with the one you just assigned:

```bash
ssh-copy-id -i ~/.ssh/insect_tracker.pub pi@192.168.1.101
```

You will be prompted for the Pi's password once. After that, the dev Pi can connect
without a password — which is what Ansible needs.

Verify it worked:

```bash
ssh -i ~/.ssh/insect_tracker pi@192.168.1.101
```

You should land directly in a terminal on the new Pi. Type `exit` to return.

---

### 1.4 Add the Pi to the inventory file

On the dev Pi, open `~/RPi_recording/ansible/inventory.ini` and add a line for the new Pi:

```ini
[pis]
pi1 ansible_host=192.168.1.101
pi2 ansible_host=192.168.1.102   # add new lines here

[pis:vars]
ansible_user=pi
ansible_ssh_private_key_file=~/.ssh/insect_tracker
```

Save the file, then commit and push the change:

```bash
cd ~/RPi_recording
git add ansible/inventory.ini
git commit -m "add pi2 to inventory"
git push
```

---

### 1.5 Create the unit config for the new Pi

Each Pi has a small config file with its hardware-specific values. Create one for the new Pi:

```bash
cp ~/RPi_recording/ansible/host_vars/template.yml \
   ~/RPi_recording/ansible/host_vars/pi2.yml
```

Open `pi2.yml` and fill in the values for this rig:

```yaml
unit_id: pi2
arena_width_cm: 30
arena_height_cm: 20
lens_calibration_file: calib_pi2.json   # generated during camera calibration
```

!!! note
    `host_vars/` is listed in `.gitignore` — these files are never committed to GitHub,
    because they contain hardware-specific values that differ between units.

---

## Part 2 — Bootstrap via the Manager app

Once Part 1 is complete, open the **Manager app** on the dev Pi and use the
**Add new Pi** button, selecting the Pi you just added. The app will:

1. Install system packages (`git`, `python3-venv`, `ffmpeg`, `libcamera-tools`)
2. Clone the repository onto the Pi
3. Create a Python virtual environment and install all dependencies
4. Deploy the unit config file

This takes 2–5 minutes. The app shows live progress and reports any errors.

!!! tip "Adding multiple Pis at once"
    Complete Part 1 for all new Pis first (flash, static IP, SSH key, inventory entry,
    unit config), then run bootstrapping once — it targets all unconfigured Pis in one pass.

---

## Verify

After bootstrapping, confirm the new Pi is healthy:

```bash
ansible pis -i ~/RPi_recording/ansible/inventory.ini -m ping
```

All Pis in the inventory should respond with `pong`. If the new Pi does not respond,
re-check the static IP and SSH key steps.
