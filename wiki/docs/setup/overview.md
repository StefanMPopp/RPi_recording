# Setup & maintenance overview

This section covers everything managed through the **Manager app** — a tool that runs on the
dev Pi and handles all software installation and updates across the fleet of recording Pis.

Day-to-day users of the recording rigs do not need anything in this section.

---

## The three setup tasks

| Task | When | Tool |
|---|---|---|
| [Set up the dev Pi](dev_pi.md) | Once, at the start of the project | Manual (follow instructions) |
| [Add a new Pi](add_pi.md) | When adding a rig to the fleet | Manager app |
| [Update Pis](update_pis.md) | When software changes are pushed | Manager app |

---

## How the system works

All recording Pis run identical software, versioned and stored on GitHub. The Manager app
uses **Ansible** — a tool that connects to each Pi over the network and enforces that every
Pi is in the correct state — to install or update that software across all Pis simultaneously.

The dev Pi is the only machine that runs the Manager app. The other Pis only need to be
powered on and connected to the network when a setup or update task runs.

```
Dev Pi  ──(Ansible via SSH)──►  Pi 1
                              ►  Pi 2
                              ►  Pi 3  …
```

See the [Add a new Pi](add_pi.md) page for a full explanation of how this works.
