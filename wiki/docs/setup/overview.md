# Setup & maintenance overview

This section is for whoever maintains the rigs. Experimenters do not need it.

---

## The model

```
        dev Pi                GitHub              recording Pis
   ┌──────────────┐      ┌────────────┐      ┌────┬────┬────┐
   │ edit + test  │─push─▶│ source of  │      │ pi1│ pi2│ …  │
   │ run Ansible  │       │   truth    │      └────┴────┴────┘
   └──────┬───────┘      └─────┬──────┘            ▲
          │                    │                   │
          └────── ansible tells each Pi to pull ───┘
```

Three rules keep eight rigs identical:

1. **Code is only ever edited on the dev Pi**, then pushed to GitHub
2. **Recording Pis only ever pull** — they are never edited directly
3. **Updates go to all Pis at once** with one command

Breaking rule 2 is the usual way fleets drift apart. A fix made directly on
rig 3 exists only on rig 3, and will be silently overwritten at the next update.

!!! warning "The dev Pi is the single point of failure"
    It holds the SSH key and the `host_vars` files, and neither is in Git. With
    a backup, replacing it takes half an hour; without one, it takes an
    afternoon and every rig must be re-keyed by hand. See
    [Replace the dev Pi](replace_dev_pi.md).

---

## Tasks

| Task | How often | Page |
|---|---|---|
| Set up the dev Pi | Once, ever | [Set up the dev Pi](dev_pi.md) |
| Add a recording Pi | When adding a rig | [Add a new Pi](add_pi.md) |
| Push a software update | Whenever code changes | [Update all Pis](update_pis.md) |
| Replace or hand over the dev Pi | On upgrade, failure, or handover | [Replace the dev Pi](replace_dev_pi.md) |
| Routine checks and fixes | Ongoing | [Day-to-day maintenance](maintenance.md) |

---

## What each machine needs

| | Dev Pi | Recording Pi |
|---|---|---|
| Raspberry Pi OS | 64-bit with desktop | 64-bit with desktop |
| Git | ✓ | ✓ |
| Ansible | ✓ | — |
| SSH key | ✓ (holds the key) | ✓ (accepts it) |
| Static IP | recommended | **required** |
| Repo clone | ✓ | ✓ |
| Camera | optional | ✓ |

Recording Pis need the desktop version because the recorder app is a graphical
application shown on the rig's monitor.

---

## Prerequisites for any maintenance task

- All target Pis powered on and on the network
- The dev Pi on the same network
- No recording in progress on the target Pis

Recording Pis need no interaction during an update — no login, no keyboard.
Powered on and reachable is enough.

!!! note "The Manager app"
    A graphical Manager app to replace the Ansible commands below is planned but
    **not yet built**. Until then, these pages give the commands directly. When
    it exists, the commands will still work — the app is a front end for the
    same playbooks.
