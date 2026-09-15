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
ssh-keygen -t ed25519 -f ~/.ssh/rig_recording
```

Press ++enter++ at both prompts for no passphrase. Two files appear:

| File | Role |
|---|---|
| `~/.ssh/rig_recording` | **Private key** — never leaves this Pi |
| `~/.ssh/rig_recording.pub` | **Public key** — safe to copy anywhere |

Tell SSH to use it for GitHub:

```bash
nano ~/.ssh/config
```

Add:

```
Host github.com
    IdentityFile ~/.ssh/rig_recording
    User git
```

Save with ++ctrl+o++, ++enter++, then ++ctrl+x++.

---

## 4. Give GitHub the public key

```bash
cat ~/.ssh/rig_recording.pub
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

## 5. Generate a read-only key for the recording rigs

!!! info "Different from the key above"
    The key in steps 3–4 belongs to the dev Pi alone and has **write access** —
    it must never be copied anywhere else. Every recording rig also needs to
    reach GitHub, since bootstrapping clones the repo **on the rig itself**,
    not on the dev Pi. A second, **read-only** key is generated once here and
    distributed to every rig automatically by `bootstrap.yml`.

```bash
cd ~/RPi_recording/ansible
mkdir -p files
ssh-keygen -t ed25519 -f files/github_deploy_ro -C "rig read-only" -N ""
cat files/github_deploy_ro.pub
```

Add it on GitHub the same way as before, but **leave "Allow write access"
unticked**:

**Repository → Settings → Deploy keys → Add deploy key**

- Title: `rig-readonly`
- Key: paste it
- Leave write access **off**

This key lives at `ansible/files/github_deploy_ro` and is never committed —
`bootstrap.yml` copies it onto each rig over the SSH connection Ansible
already has, the same way it copies the unit config. You only do this once;
every current and future rig picks it up automatically the next time it's
bootstrapped.

!!! warning "Back this up like the SSH key and host_vars"
    It exists only in `ansible/files/` on the dev Pi. See the
    [handover checklist](../reference/handover.md).

---

## 6. Set your Git identity

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
git config --global pull.rebase false
```

Without the first two, commits are refused. The third sets merge as the default
strategy so `git pull` does not stop to ask.

---

## 7. Clone the repository

```bash
git clone git@github.com:StefanMPopp/RPi_recording.git ~/RPi_recording
```

---

## 8. Install the recorder app's dependencies

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

## 9. Install the wiki tooling (optional)

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

## 10. Set a static IP

Reserve an address for the dev Pi in your router's admin panel, the same way as
for the rigs. Suggested: `192.168.50.100`.

---

## Done

Now [add your first recording Pi](add_pi.md).
