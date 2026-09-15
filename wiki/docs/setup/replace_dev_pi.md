# Replace or migrate the dev Pi

The dev Pi holds two things that exist nowhere else: the **SSH private key**
and the **`host_vars` files**. Everything else is in Git.

Whether this is a ten-minute job or an afternoon depends entirely on one
question:

!!! question "Is the old dev Pi still readable?"
    **Yes** → [Migration](#migration-old-machine-still-works). Copy the key
    across and the rigs never know anything changed.

    **No** → [Recovery](#recovery-old-machine-is-gone). You must generate a new
    key and re-authorise all eight rigs using their passwords.

Read [what makes a dev Pi](#what-makes-a-dev-pi) first if you are unsure what
needs to move.

---

## What makes a dev Pi

| Component | Where it comes from | Replaceable? |
|---|---|---|
| Raspberry Pi OS, Git, Ansible | Reinstall | Trivially |
| Repository clone | `git clone` | Trivially |
| `~/.ssh/rig_recording` | **Generated once** | Only by re-keying every rig |
| `ansible/host_vars/*.yml` | **Written by hand** | Only by re-measuring every rig |
| `git config` identity | Two commands | Trivially |
| Recorder app dependencies | apt + pip | Trivially |

Only rows three and four matter. They are the entire reason this page exists.

!!! note "There is nothing special about the machine"
    "Dev Pi" is a role, not a configuration. Any machine with the key, the
    repo, and Ansible can manage the fleet — including a laptop. It does not
    even have to be a Raspberry Pi, though having one makes testing the
    recorder app against a real camera much easier.

---

## Migration (old machine still works)

The good case. Roughly 30 minutes, most of it installation.

### 1. Back up from the old dev Pi

```bash
mkdir -p ~/devpi_migration
cp ~/.ssh/rig_recording      ~/devpi_migration/
cp ~/.ssh/rig_recording.pub  ~/devpi_migration/
cp -r ~/RPi_recording/ansible/host_vars ~/devpi_migration/
```

Copy `~/devpi_migration` to a USB stick — **not** into the repository, and not
anywhere shared.

Also note down, since they are not in any file:

- [ ] The router admin login
- [ ] The recording Pis' username and password
- [ ] Which physical rig is which `piN`

### 2. Set up the new machine

Follow [Set up the dev Pi](dev_pi.md) steps 1, 2, 5 and 7 — flash the OS,
install Git and Ansible, set the Git identity, install the app dependencies.

**Skip steps 3 and 4** (generating a key, adding it to GitHub). You are
reusing the existing key rather than making a new one.

### 3. Restore the key

```bash
mkdir -p ~/.ssh
cp /media/usb/devpi_migration/rig_recording*  ~/.ssh/
chmod 700 ~/.ssh
chmod 600 ~/.ssh/rig_recording
chmod 644 ~/.ssh/rig_recording.pub
```

!!! warning "The permissions are not optional"
    SSH silently refuses to use a private key that other users can read. If
    `chmod 600` is skipped, every connection fails with `Permission denied
    (publickey)` and nothing explains why.

Point SSH at it for GitHub:

```bash
nano ~/.ssh/config
```

```
Host github.com
    IdentityFile ~/.ssh/rig_recording
    User git
```

Test:

```bash
ssh -T git@github.com
```

A greeting with your username means the key works and GitHub still accepts it.

### 4. Clone and restore host_vars

```bash
git clone git@github.com:StefanMPopp/RPi_recording.git ~/RPi_recording
cp /media/usb/devpi_migration/host_vars/*.yml ~/RPi_recording/ansible/host_vars/
```

### 5. Verify

```bash
cd ~/RPi_recording/ansible
ansible pis -m ping          # all rigs answer pong
ansible-playbook status.yml  # full health check
```

If every rig answers, the migration is done. The rigs are unaware anything
changed — they authenticate the key, not the machine.

### 6. Give the new machine a static IP

Reserve one in the router, as for any rig. Reusing the old dev Pi's address
keeps things tidy.

### 7. Retire the old machine

Once verified, **wipe the old dev Pi rather than shelving it**. It holds a
private key granting access to every rig and write access to the repository.

```bash
shred -u ~/.ssh/rig_recording
```

Then reflash the card if it is being reused.

---

## Recovery (old machine is gone)

The dev Pi died, the card is unreadable, and nobody backed up the key. Annoying
but not serious — nothing is lost permanently, because the rigs can still be
reached with their passwords.

Budget an afternoon, mostly for step 4.

### 1. Build a new dev Pi from scratch

Follow [Set up the dev Pi](dev_pi.md) in full, **including** generating a new
key. You now have a working machine with a key no rig recognises.

### 2. Authorise the new key on GitHub

The old deploy key still sits in the repository settings, pointing at a machine
that no longer exists.

1. **GitHub → repository → Settings → Deploy keys**
2. Delete the old key
3. Add the new `~/.ssh/rig_recording.pub`, **with write access ticked**

### 3. Clone the repository

```bash
git clone git@github.com:StefanMPopp/RPi_recording.git ~/RPi_recording
```

`inventory.ini` comes back with the clone, so you already know every rig's
address.

### 4. Re-authorise every rig

This is the slow part. Each rig must be told about the new key, using its
password:

```bash
for n in 1 2 3 4 5 6 7 8; do
    ssh-copy-id -i ~/.ssh/rig_recording.pub pi@pi${n}.local
done
```

You will be prompted for the password once per rig. Adjust the range to match
your `inventory.ini`. If your rigs use static IPs instead of hostnames,
substitute those.

Then verify:

```bash
cd ~/RPi_recording/ansible
ansible pis -m ping
```

!!! danger "If the rigs' password is also lost"
    Then remote access is gone entirely and each rig must be handled physically:
    attach a keyboard and monitor and either add the key locally, or reflash the
    card and bootstrap it fresh.

    The recordings on the SD cards are still safe — this is an access problem,
    not a data problem.

### 5. Rebuild host_vars

These were never in Git, so they must be reconstructed:

```bash
cd ~/RPi_recording/ansible
cp host_vars/template.yml host_vars/pi1.yml
# repeat for each rig, then edit each one
```

Two shortcuts before measuring anything by hand:

**The rigs still have their deployed copy.** `bootstrap.yml` wrote
`config_unit.yaml` onto each Pi, and it survives:

```bash
ansible pis -a "cat /home/pi/RPi_recording/config_unit.yaml"
```

That gives you `unit_id`, arena dimensions and notes for every rig at once —
usually everything you need.

**Past recordings contain the scale.** Any `_metadata.yaml` records the
calibration in use at the time:

```yaml
scale:
  px_per_cm: 63.38
  frame_width_cm: 32.0
```

### 6. Re-lock the old key

If the old dev Pi was lost rather than destroyed — stolen, or a card that might
be readable by someone else — the old key should be treated as compromised.
Removing its deploy key from GitHub (step 2) blocks repository access, but the
rigs still trust it.

To fully revoke it, on each rig remove the old key's line from
`~/.ssh/authorized_keys`. With the new key working, Ansible can do this:

```bash
ansible pis -m ansible.posix.authorized_key \
  -a "user=pi state=absent key='$(cat /path/to/old_key.pub)'"
```

If the old public key is also lost, edit `~/.ssh/authorized_keys` on each rig
by hand and delete the unrecognised entry.

---

## Handover to another person

Migration and handover are the same operation with one decision added: **does
the new maintainer get the existing key, or their own?**

=== "Their own key (recommended)"
    Cleaner, and revocable independently.

    1. They follow [Set up the dev Pi](dev_pi.md) in full on their own machine
    2. Add their public key to GitHub as a **second** deploy key
    3. `ssh-copy-id` their key to each rig — rigs accept any number of keys
    4. You send them your `host_vars` files (these are not secret, just
       unversioned)

    Both dev Pis now work simultaneously. When you leave, your key is removed
    from GitHub and from the rigs' `authorized_keys`, and theirs keeps working.

    Worth doing even for a temporary overlap: it means the handover can be
    tested while you are still around to fix it.

=== "Share the existing key"
    Faster, but the key cannot then be revoked without re-keying everything.

    Follow [Migration](#migration-old-machine-still-works), copying the key to
    their machine. Reasonable for a permanent handover where you are leaving
    anyway, poor for a temporary or partial one.

### Handover checklist

Beyond the files, walk through:

- [ ] Run `ansible-playbook status.yml` together, so they see healthy output
- [ ] Make a trivial change, push it, run `update.yml` — the whole chain, while
      nothing is at stake
- [ ] Walk the rigs physically, matching each to its `piN` name
- [ ] Do one real recording end to end
- [ ] Hand over the router login and the rigs' password
- [ ] Point them at the [handover checklist](../reference/handover.md), which
      covers the knowledge rather than the mechanics

---

## Preventing all of this

Two commands, occasionally:

```bash
mkdir -p ~/devpi_backup
cp ~/.ssh/rig_recording* ~/RPi_recording/ansible/host_vars/*.yml ~/devpi_backup/
```

Copy that folder somewhere off the Pi — institutional storage, an encrypted USB
stick, anywhere that is not the machine it protects against losing.

With that backup, replacing a dead dev Pi is the 30-minute
[migration](#migration-old-machine-still-works) rather than the afternoon-long
[recovery](#recovery-old-machine-is-gone).

!!! danger "Do not commit the private key"
    `~/.ssh/rig_recording` grants access to every rig and write access to the
    repository. It must never go into Git, not even a private repository —
    Git history is very hard to purge, and a repository's audience tends to
    grow over time.
