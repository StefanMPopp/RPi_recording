# RPi Recording

Video recording rigs for insect behaviour experiments — eight identical Raspberry Pi
setups that record video or image stacks of a ~30 × 20 cm arena.

---

## I want to…

<div class="grid cards" markdown>

- **Record an experiment**

    Start here if you are running trials. You do not need to know anything about
    the software internals.

    → [Recording overview](recording/overview.md)

- **Add a Pi, or update the software**

    For whoever maintains the rigs. Requires the dev Pi and some terminal use.

    → [Setup & maintenance](setup/overview.md)

- **Change the code, or take over the project**

    Architecture, file formats, and the reasoning behind the design decisions.

    → [Developer reference](reference/overview.md)

</div>

---

## What the system does

Each rig records an arena from directly above and writes two things:

1. **A video file or a folder of images** — the footage itself
2. **A metadata file** (`.yaml`) — who recorded it, what the treatment was, the
   camera settings, the spatial scale, and what actually happened during capture
   (duration, frames written, frames dropped)

The metadata travels with the footage so that a recording can be interpreted
later without asking anyone what the settings were. Tracking and analysis happen
in a **separate repository** — this project ends when the files are on the
analysis machine.

---

## Hardware

Each of the eight rigs consists of:

| Component | Detail |
|---|---|
| Computer | Raspberry Pi 4 |
| Camera | Raspberry Pi HQ camera (Sony IMX477 sensor) |
| Lens | 16 mm C-mount, with C–CS adapter ring |
| Storage | 32–64 GB U30-rated SD card |
| Lighting | LED panels on an aluminium extrusion frame |
| Arena | ~30 × 20 cm |

One further Pi is the **dev Pi**. It is not a recording rig — it is where the
software is developed and from where all other Pis are updated.

!!! warning "The C–CS adapter ring is not optional"
    The HQ camera has a CS-mount throat; the 16 mm lens is C-mount. Without the
    5 mm adapter ring between them, the focal plane sits behind the sensor and
    **nothing will ever come into focus**, no matter how you turn the focus ring.
    If a rig will not focus, check for the adapter before anything else.

---

## Two roles, two kinds of work

The system deliberately separates two audiences:

**Experimenters** open the recorder app on a rig, fill in metadata, and record.
Nothing in the Setup or Developer sections is needed.

**The maintainer** (one person) works on the dev Pi, pushes code to GitHub, and
runs a single command to update all eight rigs at once. Recording Pis are never
edited directly.

This separation is what keeps eight rigs identical. If someone fixes a bug
directly on rig 3, that fix exists only on rig 3 and will be silently
overwritten at the next update.
