# Handover checklist

For whoever takes over the rigs. This page covers the *knowledge*; for the
mechanics of moving to a new machine or issuing a second key, see
[Replace the dev Pi](../setup/replace_dev_pi.md).

---

## Credentials and access

- [ ] **GitHub** — access to `StefanMPopp/RPi_recording`, with push rights
- [ ] **Dev Pi** — username and password
- [ ] **Recording Pis** — username and password (same across rigs)
- [ ] **Router** — admin login, for the static IP reservations
- [ ] **SSH key** — `~/.ssh/rig_recording` and `.pub` on the dev Pi

!!! danger "The SSH key is the critical item"
    `~/.ssh/rig_recording` grants access to every rig and write access to the
    repository. It exists **only on the dev Pi** unless someone backed it up.

    If it is lost: generate a new one, add it to GitHub as a deploy key, and
    `ssh-copy-id` it to all eight rigs using their passwords. Recoverable, but
    an afternoon's work — see
    [Recovery](../setup/replace_dev_pi.md#recovery-old-machine-is-gone).

---

## Files that exist nowhere else

Not in Git, by design. Copy them before the dev Pi is wiped:

```bash
mkdir -p ~/rig_backup
cp ~/.ssh/rig_recording*                    ~/rig_backup/
cp -r ~/RPi_recording/ansible/host_vars      ~/rig_backup/
cp ~/RPi_recording/ansible/inventory.ini     ~/rig_backup/
```

| File | Why it matters |
|---|---|
| `~/.ssh/rig_recording` | Access to everything |
| `ansible/host_vars/*.yml` | Each rig's arena dimensions and identity |
| `ansible/inventory.ini` | Which Pis exist and at which addresses (this one *is* in Git, but keep a copy) |

`config_app.yaml` on each rig is **not** worth backing up — it holds a write
speed measurement, regenerated in fifteen seconds by
**Settings → Recalibrate write speed**.

---

## Physical inventory

- [ ] 8 recording rigs — location of each
- [ ] 1 dev Pi
- [ ] Spare SD cards, ideally pre-flashed
- [ ] Spare ribbon cables — these fail more often than cameras
- [ ] **Spare C–CS adapter rings** — the most common single point of failure
- [ ] Spare power supplies

---

## Knowledge worth transferring

Things that are easy to get wrong and expensive to rediscover:

1. **The C–CS ring.** If a rig will not focus, check for it before anything
   else. See [camera notes](camera_notes.md).

2. **Never edit code on a recording Pi.** Changes exist on one rig, are
   invisible, and are destroyed at the next update. Dev Pi → GitHub → rigs.

3. **`1332 × 990` sees only ~66% of the scene.** It will crop a full-arena
   view. Use `2028 × 1520` for high framerates with the whole arena.

4. **Greyscale unless colour is genuinely needed.** Three times smaller, no loss
   for tracking.

5. **H.264 is risky for tracking.** Inter-frame compression puts artefacts
   exactly on moving subjects. Validate before committing an experiment to it.

6. **Recalibrate write speed after any SD card swap.** Otherwise the headroom
   estimates describe a card that is no longer present.

7. **Watch queue depth, not just dropped frames.** It rises before frames are
   lost, so it is the warning rather than the symptom.

---

## First week

1. Read the [recording overview](../recording/overview.md) and run a test
   recording on one rig
2. Run `ansible pis -i inventory.ini -m ping` from the dev Pi — confirm all
   eight answer
3. Make a trivial change (a comment), push it, and run `update.yml`. Confirm it
   reaches the rigs. This exercises the whole chain while nothing is at stake
4. Back up the files listed above
5. Read [camera notes](camera_notes.md) — most field problems are in there

---

## Current state and open work

**Working:** the recorder app in full — preview with zoom and pan, four
formats, greyscale and colour, metadata sidecars, profiles, CSV metadata lists
with automatic advance, write-speed benchmarking and headroom estimates.

**Not built yet:**

| Item | Notes |
|---|---|
| **Manager app** | Graphical front end for the Ansible playbooks. The playbooks work; this would only remove the terminal step. |
| **Automated data transfer** | Currently a manual `rsync`; see [maintenance](../setup/maintenance.md). |
| **Hardware H.264 encoding** | Would be faster at high resolution, at the cost of per-frame drop visibility. Deliberately deferred. |

**Deliberately out of scope:** tracking and analysis. Separate repository, runs
on the analysis machine, not on the Pis.

---

## Where things live

| | |
|---|---|
| Code and wiki source | GitHub, `main` branch |
| Published wiki | `https://stefanmpopp.github.io/RPi_recording/` |
| Wiki HTML | GitHub, `gh-pages` branch — generated, never edit |
| Recordings | Rig SD cards until copied to the analysis machine |
| Per-rig config | `ansible/host_vars/` on the dev Pi only |
