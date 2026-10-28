# Choosing settings

How to pick resolution, framerate, color mode and format for an experiment.

---

## Start from the animal, not the camera

Two questions decide almost everything:

1. **How fast does the behavior happen?** → sets the framerate
2. **How small is the feature you need to resolve?** → sets the resolution

Everything else follows. Recording at maximum settings "to be safe" produces
enormous files, risks dropped frames, and rarely improves the tracking.

---

## Framerate

| Behavior | Suggested fps |
|---|---|
| Slow movement, position over time | 5–15 |
| General locomotion, trail following | 15–30 |
| Fast movement, interactions | 30–60 |
| Rapid events (strikes, escapes) | 60+ |
| Timelapse, colony-level change | 0.1–2 |

For most tracking, the framerate needs to be high enough that an individual
moves less than about its own body length between frames. Faster than that adds
data without adding information.

Framerate is the **cheapest lever on file size** — halving it halves the data
rate exactly, with no loss of spatial detail.

---

## Sensor modes and field of view

The IMX477 offers several modes. They differ in two independent ways: the number
of pixels, and **how much of the sensor is read**.

| Mode | Max fps | Field of view |
|---|---|---|
| 4056 × 3040 | ~17 | Full |
| 2028 × 1520 | ~66 | Full (2×2 binned) |
| 2028 × 1080 | ~92 | Full width, cropped height |
| 1332 × 990 | ~148 | **~66% of the width** |

!!! warning "Cropped modes see a smaller area"
    `1332 × 990` reads only the central part of the sensor. With the arena
    filling the frame at full field of view, this mode will **cut off the
    edges** — not merely show them at lower resolution. Modes with reduced field
    of view are marked `[NN% FoV]` in the dropdown.

**For a 30 × 20 cm arena that must stay fully in frame, `2028 × 1520` is
usually the right choice.** It keeps the full field of view and allows up to
66 fps.

---

## Recording only part of the frame

When only part of the arena matters — a trail, a bridge, a nest entrance —
tick **Crop** and record just that rectangle. Copying, encoding and writing all
scale with the pixels recorded, so a thin strip records far faster and smaller
than the full frame.

Measured on a Pi 4, grayscale, a strip 256 rows tall across the full width:

| Mode | Full frame, fastest format | Strip, every format |
|---|---|---|
| 4056 × 3040 | ~4 fps | 17.3 fps (sensor max) |
| 4056 × 2160 | ~6 fps | 24.3 fps (sensor max) |
| 2028 × 1520 | ~18 fps | 62–65 fps |

**A crop cannot exceed the sensor mode's maximum fps**: the sensor still reads
the whole mode, and the crop is taken afterward. For more fps, choose a faster
mode and crop that. Above about 60 fps the processor becomes the limit, and
color strips are limited by encoding sooner than grayscale ones.

Crops up to 1920 px wide use the Pi's hardware H.264 encoder even in the
4056-wide modes.

The crop stays on the same part of the scene when you change sensor mode. A
mode that sees less of the sensor (1332 × 990) clips it to what it can see.

---

## Color mode

Use **grayscale** unless the analysis needs color. Tracking works on
brightness; the color channels add data without adding usable signal.

| | Image stacks | MJPEG | H.264 |
|---|---|---|---|
| Grayscale saving | ~3× | ~2.5× | ~1.5× |

Choose color only for things like distinguishing color-marked individuals or
recording color-dependent behavior.

---

## Format

See [file formats](../reference/file_formats.md) for the full comparison. Short
version:

| Format | Use when |
|---|---|
| **MJPEG (.avi)** | Default for tracking. Every frame independent, no motion artifacts |
| **TIFF stack** | Highest fidelity needed, low framerate, storage not a concern |
| **PNG stack** | Lossless but smaller than TIFF; only below ~15 fps |
| **H.264 (.mp4)** | Long recordings where storage dominates — with the caveat below |

!!! warning "H.264 and tracking"
    H.264 compresses by describing how frames *differ* from one another. On
    fast-moving subjects this produces blocky artifacts exactly where the animal
    is, which is exactly where the tracker is looking. It is excellent for
    reviewing footage by eye and risky for automated tracking. If storage forces
    it, validate the tracking on a short H.264 clip before committing a whole
    experiment to it.

---

## Maximum frame rate

Every recording is capped by the slowest of three stages, and which one binds
depends on resolution, color mode **and** format:

| Limit | What it is | Typical when |
|---|---|---|
| **sensor** | The sensor mode's maximum fps | Small frames, or a thin crop |
| **CPU** | Capture falls behind while encoding shares the processor | High fps with compressed formats |
| **encoding** | Compressing each frame | MJPEG and compressed stacks at high resolution |
| **SD card** | Writing the bytes | Uncompressed stacks at high resolution |

Nothing here is estimated. Run **Settings → Measure maximum fps** once for a
resolution and color mode: it records each format flat out for a few seconds
(about 25 s in total). The ⓘ next to **Format** then shows one table — the
maximum fps of every format, what limits it, megabytes per frame, and how long a
recording fits on the card. The line under the selector summarizes the chosen
format and turns red if the selected frame rate is above its maximum.

Measurements are stored per sensor mode, recorded frame size (see
[crop](#recording-only-part-of-the-frame)) and color mode, so switching to an
unmeasured combination shows it as not measured.

### If the frame rate you need is above the maximum

Read the **Limited by** column — the fix depends on it:

- **sensor** — choose a faster sensor mode; nothing else helps.
  `2028 × 1520` keeps the full field of view at a quarter of the pixels.
- **CPU** — record a smaller crop, choose a format that is cheaper to encode
  (TIFF needs the least CPU), or switch to grayscale.
- **encoding** — choose a faster format (the table shows which), switch to
  grayscale, or lower the resolution.
- **SD card** — choose a format with smaller frames, switch to grayscale, or
  use a faster card. The stack formats are written uncompressed by default for
  speed; if the card is what limits them, a compressed setting may record
  faster (see [file formats](../reference/file_formats.md)).

!!! note "Measure the card once per card"
    The SD card limit uses a write speed measured per card
    (**Settings → Recalibrate write speed**, run automatically by the first fps
    measurement). Re-run it after swapping the card. Cards also slow as they fill
    and age.

---

## Worked examples

=== "Ant trail following"
    Slow, needs whole arena, long recordings.

    - 2028 × 1520, full field of view
    - 15 fps
    - Grayscale
    - MJPEG

=== "Fly escape responses"
    Fast, short, small area of interest.

    - 1332 × 990 (cropped field of view is fine — the event is central)
    - 120 fps
    - Grayscale
    - MJPEG

=== "Colony-level timelapse"
    Very slow, very long, maximum detail.

    - 4056 × 3040
    - 0.5 fps
    - Grayscale
    - PNG stack (slow encoding is irrelevant at this framerate)

=== "Color-marked individuals"
    Needs hue, moderate speed.

    - 2028 × 1520
    - 30 fps
    - **Color**
    - MJPEG — measure first: color roughly triples the data per frame
