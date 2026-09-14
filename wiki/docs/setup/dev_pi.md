# Set up the dev Pi

!!! warning "One-time setup — most people can skip this page"
    Only needed when building the dev Pi for the first time. If it already
    works, go to [Add a new Pi](add_pi.md).

    **Replacing an existing dev Pi?** Use
    [Replace the dev Pi](replace_dev_pi.md) instead. Following this page
    would generate a new SSH key that none of the rigs recognise.

The dev Pi is where code is written and from where all rigs are updated. It is
the only machine that pushes to GitHub.

This setup is manual, because the tooling that automates everything else lives
on this machine and does not exist yet at this point.

---

## What you need

- A Raspberry Pi 4 and SD card (32 GB or more)
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on any computer
- A GitHub account with access to the `RPi_recording` repository
- The Pi on the same network as the rigs

---

## 1. Flash the OS

1. Open Raspberry Pi Imager
2. OS: **Raspberry Pi OS (64-bit)** — the full desktop version
3. Select the SD card
4. Open **advanced options** (gear icon) and set:
     - Hostname: `devpi`
     - **Enable SSH**, with password authentication
     - Username and password — note them down
     - Wi-Fi, if not using ethernet
5. Flash, insert, boot

---

## 2. Install Git and Ansible

```bash
sudo apt update
sudo apt install -y git ansible
```

- **Git** — version control, syncs code with GitHub
- **Ansible** — runs commands on all rigs over SSH

---

## 3. Generate an SSH key

An SSH key lets this Pi connect to GitHub and to the rigs without typing a
password each time.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/insect_tracker
```

Press ++enter++ at both prompts for no passphrase. Two files appear:

| File | Role |
|---|---|
| `~/.ssh/insect_tracker` | **Private key** — never leaves this Pi |
| `~/.ssh/insect_tracker.pub` | **Public key** — safe to copy anywhere |

Tell SSH to use it for GitHub:

```bash
nano ~/.ssh/config
```

Add:

```
Host github.com
    IdentityFile ~/.ssh/insect_tracker
    User git
```

Save with ++ctrl+o++, ++enter++, then ++ctrl+x++.

---

## 4. Give GitHub the public key

```bash
cat ~/.ssh/insect_tracker.pub
```

Copy the whole line, then on GitHub:

**Repository → Settings → Deploy keys → Add deploy key**

- Title: `devpi`
- Key: paste it
- **Tick "Allow write access"** — the dev Pi must push, not only pull

Test it:

```bash
ssh -T git@github.com
```

You should see a greeting with your username. `Permission denied (publickey)`
means the key was not accepted — check the `~/.ssh/config` above and that the
deploy key was saved.

---

## 5. Set your Git identity

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
git config --global pull.rebase false
```

Without the first two, commits are refused. The third sets merge as the default
strategy so `git pull` does not stop to ask.

---

## 6. Clone the repository

```bash
git clone git@github.com:StefanMPopp/RPi_recording.git ~/RPi_recording
```

---

## 7. Install the recorder app's dependencies

Even on the dev Pi, so it can be tested locally:

```bash
sudo apt install -y python3-pyqt6 python3-picamera2 python3-opencv
pip install pyyaml --break-system-packages
```

!!! note "Why apt rather than pip for the big three"
    `picamera2` needs system libraries pip cannot supply; `PyQt6` and `opencv`
    have prebuilt ARM packages in apt that avoid a very long compile. Only
    `pyyaml` comes from pip.

    `--break-system-packages` is required on Raspberry Pi OS and is harmless
    here — it bypasses a warning aimed at protecting system Python.

Check it runs:

```bash
cd ~/RPi_recording
python3 recorder_app/main.py
```

---

## 8. Install the wiki tooling (optional)

To edit and publish these pages:

```bash
pip install mkdocs mkdocs-material --break-system-packages
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Preview locally:

```bash
cd ~/RPi_recording/wiki
mkdocs serve      # then open http://localhost:8000
```

Publish:

```bash
mkdocs gh-deploy
```

!!! info "How gh-deploy works"
    It builds the site and pushes it to a separate `gh-pages` branch. **Do not
    merge that branch into `main`** — it holds generated HTML, not source. Your
    Markdown lives on `main`; `gh-pages` is managed entirely by MkDocs.

    Enable it once under **GitHub → Settings → Pages**, source `gh-pages`,
    folder `/ (root)`.

---

## 9. Set a static IP

Reserve an address for the dev Pi in your router's admin panel, the same way as
for the rigs. Suggested: `192.168.1.100`.

---

## Done

Now [add your first recording Pi](add_pi.md).
