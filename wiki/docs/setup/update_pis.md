# Update all Pis

Getting new code onto every rig.

---

## The sequence

Updating is always three steps, and they are separate:

```
1. edit + test on the dev Pi
2. git push          → GitHub now has it
3. ansible-playbook  → the rigs now have it
```

Step 2 does not update the rigs. Step 3 does. Pushing without running the
playbook leaves the rigs behind; running the playbook without pushing gives them
nothing new to fetch.

---

## 1. Edit and test on the dev Pi

Work in `~/RPi_recording` as normal. Test before pushing:

```bash
cd ~/RPi_recording
python3 recorder_app/main.py
```

## 2. Push to GitHub

```bash
git add .
git commit -m "describe what changed"
git push
```

See what you are about to commit first with `git status`.

!!! warning "New Python package?"
    If you installed something new with pip, record it before pushing:

    ```bash
    pip freeze > recorder_app/requirements.txt
    ```

    Otherwise the rigs will pull code that imports a package they do not have.
    System packages installed with `apt` instead need a line adding to
    `bootstrap.yml` — see [working on the code](../reference/development.md).

## 3. Push to the rigs

```bash
cd ~/RPi_recording/ansible
ansible-playbook -i inventory.ini update.yml
```

This pulls the new code and syncs dependencies on every Pi at once. Only changes
are transferred — Git is incremental, so a one-line fix moves a few hundred
bytes, not the whole repository.

A single Pi:

```bash
ansible-playbook -i inventory.ini update.yml --limit pi3
```

---

## What the rigs need

Powered on and on the network. Nothing else — no login, no keyboard, no monitor.

They must not be **recording** during an update, since the files would change
underneath a running app.

---

## Checking it worked

```bash
ansible pis -i inventory.ini -a "git -C /home/pi/RPi_recording log -1 --oneline"
```

Every Pi should report the same commit as the dev Pi:

```bash
git -C ~/RPi_recording log -1 --oneline
```

---

## If an update fails

Ansible reports the task and host. Then:

| Symptom | Likely cause | Fix |
|---|---|---|
| One Pi `UNREACHABLE` | Off or off-network | Power on, wait a minute, re-run with `--limit` |
| All fail on the pip task | Broken `requirements.txt` | Fix on dev Pi, push, re-run |
| Git pull fails on one Pi | Someone edited files there | See below |
| Fails after a big change | Missing system package | Add to `bootstrap.yml`, run that instead |

### "Local changes would be overwritten"

Someone edited code directly on a recording Pi. Discard the local edits — the
repository is the source of truth:

```bash
ssh -i ~/.ssh/rig_recording pi@piN.local
cd ~/RPi_recording
git checkout -- .
exit
```

Then re-run the update. If the edit was a genuine fix, reproduce it on the dev
Pi and push it properly.

!!! danger "Never edit code on a recording Pi"
    Such changes exist on one rig only, are invisible to everyone, and are
    destroyed at the next update. Edit on the dev Pi, push, update.

### Recovering a broken Pi

`bootstrap.yml` is safe to re-run and rebuilds a Pi's environment from scratch:

```bash
ansible-playbook -i inventory.ini bootstrap.yml --limit pi3
```

---

## Rolling back

If an update breaks something in the field:

```bash
cd ~/RPi_recording
git log --oneline -10          # find the last good commit
git revert HEAD                # undo the most recent commit
git push
cd ansible
ansible-playbook -i inventory.ini update.yml
```

`git revert` is preferable to `git reset` here — it makes a new commit undoing
the change, leaving history intact and the rigs able to fast-forward normally.
