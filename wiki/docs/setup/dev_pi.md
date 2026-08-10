# Step 1: Set up the dev Pi

!!! warning "One-time setup — most people can skip this page"
    This page is only needed when setting up the dev Pi for the first time, or rebuilding it
    from scratch. If the dev Pi is already running and the Manager app is accessible,
    go directly to [Add a new Pi](add_pi.md).

The dev Pi is the central machine for managing the fleet. It runs the Manager app, holds the
Ansible configuration, and is the only machine from which code changes are pushed.

This setup is done **manually** — there is no app to help, because the app itself lives on
the dev Pi and does not exist yet at this stage.

---

## What you need

- Raspberry Pi 4 with SD card (≥ 32 GB, U30 rated)
- A computer with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed
- The dev Pi connected to the same network as the recording Pis
- A GitHub account and a private repo named `RPi_recording`

---

## 1. Flash the dev Pi

1. Open Raspberry Pi Imager on your computer.
2. Select **Raspberry Pi OS (64-bit)** as the operating system.
3. Select your SD card.
4. Click the **gear icon** (advanced options) and set:
    - Hostname: `devpi`
    - Enable SSH: **checked** (use password authentication for now)
    - Username: `pi`
    - Set a password you will remember
    - Configure your Wi-Fi network if not using ethernet
5. Flash the card and insert it into the dev Pi.

---

## 2. Install Git and Ansible

Open a terminal on the dev Pi (or SSH into it) and run:

```bash
sudo apt update
sudo apt install -y git ansible
```

`apt` is the Pi's built-in package installer. This installs:

- **Git** — version control tool for syncing code with GitHub
- **Ansible** — automation tool that manages the other Pis over the network

---

## 3. Generate an SSH key

An SSH key is a pair of files that lets the dev Pi connect to GitHub and to all other Pis
without typing a password each time. Generate one with:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/rig_recording
```

Press Enter at both prompts to leave the passphrase empty. Two files are created:

- `~/.ssh/rig_recording` — the **private key** (never share this)
- `~/.ssh/rig_recording.pub` — the **public key** (safe to share)


Tell SSH which key to use for GitHub
```bash
nano ~/.ssh/config
```

Add these lines exactly:
```bash
Host github.com
    IdentityFile ~/.ssh/rig_recording
    User git
```
Save with `Ctrl+O`, Enter, then `Ctrl+X`.
Test the connection:
```bash
ssh -T git@github.com
```
You should see: `Hi StefanMPopp! You've successfully authenticated...`

---

## 4. Add the public key to GitHub

GitHub needs the public key so that the dev Pi (and later, all other Pis) can pull code
without a password.

1. Print the public key:
    ```bash
    cat ~/.ssh/rig_recording.pub
    ```
2. Copy the entire output (one long line starting with `ssh-ed25519`).
3. On GitHub: go to your `RPi_recording` repo → **Settings** → **Deploy keys** → **Add deploy key**.
4. Paste the key, give it a name (e.g. `devpi`), and save.

---

## 5. Clone the repository

Download the repository to the dev Pi:

```bash
git clone git@github.com:StefanMPopp/RPi_recording.git ~/RPi_recording
```

This creates a folder at `~/RPi_recording` containing all project code. This is where you
will work and from which all changes are pushed to GitHub.

---

## 6. Make these wiki pages

To get it running locally on the dev Pi:
```bash
pip install mkdocs mkdocs-material --break-system-packages
cd ~/RPi_recording
mkdocs serve
# then open http://localhost:8000 in a browser
```
or `python3 -m -mkdocs serve` if the above throws an error

To publish to GitHub Pages (gives you the public URL):
```bash
mkdocs gh-deploy
```

1. Go to `github.com/StefanMPopp/RPi_recording`
2. Settings → Pages (left sidebar)
3. Under Source, select branch `gh-pages`, folder `/ (root)`
4. Save

After a minute, your wiki will be live at: `https://stefanmpopp.github.io/RPi_recording/`

From now on, to update the wiki after editing the .md files, run mkdocs gh-deploy again from ~/RPi_recording

---

## 7. Install the Manager app

```bash
cd ~/RPi_recording
pip install -r app/manager/requirements.txt --break-system-packages
```

---

## Done

The dev Pi is now ready. Proceed to [Add a new Pi](add_pi.md) to bring the first recording
Pi into the fleet.
