# Day-to-day maintenance

Routine tasks and the useful Ansible one-liners.

---

## Routine checks

### Weekly, during an active experiment

```bash
cd ~/RPi_recording/ansible
ansible pis -i inventory.ini -m ping                                    # all reachable?
ansible pis -i inventory.ini -a "df -h /"                               # disk space
ansible pis -i inventory.ini -a "vcgencmd measure_temp"                 # temperature
```

Watch for:

- **Disk above 80% full** — SD cards slow markedly when nearly full, which
  causes dropped frames on rigs that were previously fine
- **Temperature above 80 °C** — the Pi throttles, which also causes drops

### Monthly

```bash
ansible pis -i inventory.ini -a "git -C /home/pi/RPi_recording log -1 --oneline"
```

All rigs should show the same commit. A rig on an older commit missed an update.

---

## Useful one-liners

Run an arbitrary command on every Pi:

```bash
ansible pis -i inventory.ini -a "COMMAND"
```

| Purpose | Command |
|---|---|
| Free space | `-a "df -h /"` |
| Temperature | `-a "vcgencmd measure_temp"` |
| Uptime | `-a "uptime"` |
| Camera detected | `-a "libcamera-hello --list-cameras"` |
| Recordings this month | `-a "ls -la /home/pi/Projects"` |
| Current commit | `-a "git -C /home/pi/RPi_recording log -1 --oneline"` |
| Reboot | `-a "reboot" --become` |

Add `--limit piN` for a single Pi.

---

## Getting data off the rigs

Recordings are written to the rig's SD card and must be copied to the analysis
machine. From the analysis machine:

```bash
rsync -avh --progress \
    pi@pi1.local:~/Projects/ \
    /path/to/analysis/data/pi1/
```

`rsync` copies only what is missing, so it can be re-run safely and resumed
after an interruption.

!!! warning "Verify before deleting"
    Check the copy — file count and total size — before clearing the rig.
    A `_metadata.yaml` without its footage is worthless, and vice versa.

    ```bash
    ls ~/Projects | wc -l                                  # on the rig
    ls /path/to/analysis/data/pi1 | wc -l                  # on the analysis machine
    ```

### Clearing space

After verifying the copy:

```bash
ssh -i ~/.ssh/rig_recording pi@pi1.local
rm -rf ~/Projects/OLD_EXPERIMENT
```

Deliberately manual. Automating deletion of research data is not worth the risk.

---

## SD card care

SD cards are the least reliable part of the system.

- **Replace on any sign of trouble** — repeated dropped frames at settings that
  used to work, filesystem errors, failure to boot
- **Recalibrate write speed after any card swap**:
  *Settings → Recalibrate write speed* on that Pi
- **Keep spare cards pre-flashed** — a spare card turns a dead rig into a
  ten-minute swap plus a bootstrap run
- Cards slow as they age and as they fill; recalibrate occasionally on older
  cards

---

## Backups

| What | Where | Backed up how |
|---|---|---|
| Code | GitHub | Inherently |
| Wiki source | GitHub, `main` branch | Inherently |
| `ansible/host_vars/*.yml` | Dev Pi only | **Manual — do this** |
| `~/.ssh/rig_recording` | Dev Pi only | **Manual — do this** |
| `ansible/files/github_deploy_ro*` | Dev Pi only | **Manual — do this** |
| `config_app.yaml` per rig | Each rig | Not needed; regenerate by recalibrating |
| Recordings | Rig SD cards → analysis machine | Manual `rsync` |

The three manual items are the ones that hurt. Without the SSH key you lose
access to every rig and to GitHub; without the read-only key every rig fails
to bootstrap the same way pi1 did the first time; without `host_vars` you lose
each rig's configuration. Copy all three somewhere safe:

```bash
mkdir -p ~/rig_backup
cp ~/.ssh/rig_recording* ~/rig_backup/
cp -r ~/RPi_recording/ansible/host_vars ~/rig_backup/
cp ~/RPi_recording/ansible/files/github_deploy_ro* ~/rig_backup/
# then copy ~/rig_backup to a USB stick or institutional storage
```

This backup is what decides whether replacing a dead dev Pi is a half-hour job
or an afternoon — see [Replace the dev Pi](replace_dev_pi.md).

!!! danger "The private key is a credential"
    `~/.ssh/rig_recording` grants access to every rig and write access to the
    repository. Back it up somewhere private, never into the repository itself.

---

## Replacing a failed Pi

1. Flash a new SD card ([Add a new Pi](add_pi.md) steps 1.1–1.2)
2. Give it the **same hostname and static IP** as the failed one
3. Copy the SSH key to it (step 1.4)
4. Its `host_vars` file already exists — nothing to create
5. Bootstrap it:

```bash
ansible-playbook -i inventory.ini bootstrap.yml --limit pi3
```

6. Recalibrate write speed on the rig — the new card differs from the old one

Because the identity lives in the inventory and `host_vars`, the replacement is
indistinguishable from the original.
