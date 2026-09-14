# Developer reference

For whoever changes the code — including you in six months, when the reasoning
behind a decision has faded.

---

## Pages

| Page | Contents |
|---|---|
| [Repository layout](repo_layout.md) | What lives where, and what is deliberately not committed |
| [Recorder app architecture](architecture.md) | Modules, threading model, data flow |
| [File formats](file_formats.md) | Format comparison, sizes, and the tracking implications |
| [Camera notes](camera_notes.md) | IMX477 quirks that cost time to discover |
| [Working on the code](development.md) | Conventions, testing, adding features |
| [Handover checklist](handover.md) | Everything a successor needs |

---

## Design decisions worth knowing

These shaped the codebase and are not obvious from reading it.

### Config is never hardcoded

Paths, camera parameters and thresholds live in `constants.py` or a YAML file.
Eight rigs with subtly different hardcoded values would be unmaintainable.

### Intermediate data is human-inspectable

Metadata is YAML, metadata lists are CSV. Both open in any text editor and can
be diffed, grepped, and fixed by hand. A binary or database format would be
faster and would cost far more when something needs checking at 11pm before a
deadline.

### The capture path is uniform across formats

All four formats go through the same software capture loop rather than using
picamera2's hardware H.264 encoder. The hardware path is faster but gives no
per-frame visibility, cannot produce true greyscale, and would make dropped-frame
counting a guess. Honest drop reporting was judged more valuable than the speed.

If H.264 at high resolution proves too slow, a hardware fast-path can be added —
but as an option, not a replacement.

### Capture and writing are separate threads

A bounded queue sits between them. A momentary SD card stall costs queued frames
instead of disrupting capture timing, and a full queue is an unambiguous signal
that the disk cannot keep up. This is why the status panel shows queue depth: it
is the earliest warning available.

### Spatial calibration is anchored to the scene, not the pixels

Sensor modes vary in pixel count *and* in how much of the sensor they read,
independently. Storing px/cm alone would silently corrupt the scale on a mode
change. The app stores the scene width the full sensor would see and derives
everything from that. See [camera notes](camera_notes.md).

### The dev Pi is the only writer

Recording Pis pull and never push. This is a social convention enforced by
habit rather than by tooling, and it is the one most likely to be broken by a
well-meaning person fixing something in the field.

---

## Current state

**Working:** the recorder app — preview with zoom and pan, all four formats,
greyscale and colour, metadata sidecars, profiles, metadata lists with
automatic advance, write-speed benchmarking and headroom estimates.

**Not yet built:**

- **The Manager app** — a graphical front end for the Ansible playbooks.
  Everything it would do is currently done with the commands in the
  [setup section](../setup/overview.md).
- **Automated data transfer** — currently a manual `rsync`.
- **Tracking** — deliberately a separate repository; it does not run on the Pis.
