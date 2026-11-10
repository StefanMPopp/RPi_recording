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

## Exposure, gain and aperture

Open **Settings → Calibrate camera** with the arena, the lighting and the
animals in place. The orange frame starts on the whole image; drag its edges
onto the arena floor. Everything the window measures is taken from inside
that frame.

Work through it in this order. Each step fixes one variable, and later steps
depend on earlier ones.

1. **Lighting.** Make the white background as even as possible. Uneven light
   costs more than any camera setting, because one tracking threshold then
   cannot fit the whole arena.
2. **Aperture.** Run the aperture sweep, described below. It finds the f-stop
   with the sharpest corners and tells you how much light each f-stop costs.
3. **Speed.** Measure how fast the animals move. This gives the longest
   exposure time that keeps motion blur small.
4. **Exposure time.** Click **Use this exposure** next to the exposure time
   the speed section suggests.
5. **Gain.** Leave it at 1. If the background marker falls below its green
   range, add light or open the aperture by a stop. Raise the gain only as a
   last resort, because it amplifies noise along with the image.

Click **Apply**, then **File → Save profile** to keep the result.

### Why fixed exposure

Automatic exposure adjusts brightness all the time. It also aims for mid-gray,
so a mostly white arena comes out gray. Tracking tools such as idtracker.ai
segment animals with brightness thresholds, which then fit one video but not
the next, or not even the whole of one. A fixed exposure time, gain and white
balance keep every recording alike.

### The brightness check

Instead of a histogram, the window shows two markers on a black-to-white bar:

- **background**: the typical value of the arena floor. Target 200–240:
  bright, with headroom before white clips.
- **animals**: the typical value of the animals. Target 15–90: clearly dark,
  but not black, so pose estimation keeps detail inside the body.

Animals are what moves. The window builds an image of the arena from the past
few seconds, and only blobs clearly darker than that image count as animals.
Dark tape, the arena rim and shadows never move, so they are part of the
background image and are not counted. An animal that stays still for several
seconds disappears from detection until it moves again.

Pixels that are pure white are painted red on the preview, and pure black
ones blue.

### Speed, exposure time and frame rate

These two settings affect tracking in different ways:

- **Exposure time sets motion blur.** Blur merges animals that touch into one
  blob, fades legs and antennae, and makes the images trackers use to tell
  individuals apart less distinct.
- **Frame rate sets how far an animal moves between frames.** When two
  animals meet, that distance decides whether the tracker can follow which is
  which. Identity swaps after encounters are mainly a frame-rate problem.

**Measure live** follows the animals for as long as you let it run; a minute
or more of normal behavior is a good sample. **Analyze a recording…** does the
same on the first five minutes of an AVI, MP4 or image stack recorded by this
app, taking the scale and frame times from its metadata.

Both report the 95th and 99th percentile and the fastest speed while the
animals move. Resting time is left out, so it does not pull the numbers down.
The 95th percentile is filled into **Plan for**, which you can edit. From it
the window shows:

- **Exposure time**: the longest exposure that keeps the motion blur within
  **Blur allowed**, at most one frame. **Use this exposure** switches to
  Fixed with that value; the line below compares it with the exposure in use
  now.
- how far an animal moves between frames at the current frame rate, in body
  lengths once you enter the **Body length**. Up to 0.5 is good, up to 1 is
  marginal.
- the frame rate needed to stay within 0.5 body lengths per frame

**Blur allowed** is in recorded pixels, 1 px by default. Once the body length
and the scale are both entered, it is filled in from the animals' length in
pixels: 2 % of it, but at least 1 px and at most 3 px. Larger animals tolerate
more blur, but beyond a few pixels blur closes the gap between touching
animals and fades thin legs, whatever the body size. Below 1 px it makes no
difference, because the lens and the pixel grid already soften edges by about
that much. You can still edit the value; changing the body length or scale
fills it in again.

The preview shows a bar as long as the distance an animal covers in one second
at the planned speed, with a tick for every frame. Zoom in (Ctrl + scroll)
to compare it with the animals.

!!! note "Measured speeds understate encounters"
    Matches that could be wrong, such as animals touching, are left out of
    the speed measurement. If animals speed up when they meet, plan for the
    99th percentile instead.

The speed needs the scale (px/cm). The window takes it from the main window;
if it is not set there, enter it in the window.

### The aperture sweep

Animals are not needed for this; flat printed targets are better, because they
hold still between measurements.

1. Lay targets with fine black print (text, a printed checkerboard) on the
   arena floor: one in the center and one in each corner of the orange frame.
   A printed resolution test chart works too, if it reaches the corners of
   the frame: only the center and the four corners are measured.
2. Open the aperture fully (lowest f-number) and focus on the center
   target. Focus is most precise when the depth of field is shallowest. Do
   not refocus after this.
3. Set the lens ring to an f-stop, choose the same value in the window and
   click **Measure**. Exposure is automatic during the measurement, so every
   f-stop is compared at the same brightness.
4. Repeat for each f-stop up to f/8.

For each f-stop, the table shows:

| Column | Meaning |
|---|---|
| Edge center / Worst corner | How many pixels a black-to-white edge is spread over. 1 px is perfectly sharp. |
| Evenness | The darkest corner's white as a share of the center's (vignetting). |
| Light | How much more light the f-stop needs than the brightest one measured. |

The recommendation is the f-stop with the most light among those whose corners
are within 10 % of the sharpest result and whose evenness is at least 85 %.
Wide open, most lenses are soft and darken toward the corners; stopped far
down, diffraction blurs them again. Expect the best result two or three stops
above the lowest f-number.

Each full stop halves the light. Make up for it with brighter lighting rather
than a longer exposure (more motion blur) or more gain (more noise).

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
