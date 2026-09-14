# File formats

Why the four formats exist, what they cost, and which to use.

---

## The tracking constraint

Video codecs fall into two families, and the difference matters more for
tracking than for viewing.

**Intra-frame** (MJPEG, TIFF, PNG) compresses each frame independently. Every
frame stands alone, decodes identically however you seek to it, and contains no
information borrowed from its neighbours.

**Inter-frame** (H.264) stores occasional full frames and describes the rest as
*differences*. This is dramatically more efficient — and it concentrates its
errors precisely where things move.

For a tracker, that is the worst possible place to put an artefact. The moving
animal is both the thing being measured and the thing the codec approximates
most aggressively. Blocking artefacts around a moving subject shift the apparent
centroid, and the error correlates with speed, which is often the variable of
interest.

**Hence the default is MJPEG**, despite files roughly ten times larger than
H.264.

---

## The four formats

| Format | Compression | Independent frames | Tracking |
|---|---|---|---|
| **MJPEG (.avi)** | Lossy, per frame | ✓ | Recommended |
| **TIFF stack** | None | ✓ | Ideal, large |
| **PNG stack** | Lossless, per frame | ✓ | Ideal, slow to write |
| **H.264 (.mp4)** | Lossy, inter-frame | ✗ | Use with care |

---

## Size estimates

Approximate, static scene, **greyscale**. Colour is roughly 2.5–3× more.

### 2028 × 1520 (recommended for a full-arena view)

| Format | 15 fps | 30 fps | 60 fps |
|---|---|---|---|
| TIFF stack | 2.6 GB/min | 5.2 GB/min | 10.4 GB/min |
| PNG stack | 260 MB/min | 520 MB/min | — |
| MJPEG | 340 MB/min | 680 MB/min | 1.4 GB/min |
| H.264 | 25 MB/min | 50 MB/min | 100 MB/min |

### 4056 × 3040 (full resolution)

| Format | 5 fps | 10 fps | 17 fps |
|---|---|---|---|
| TIFF stack | 3.5 GB/min | 7 GB/min | 11.9 GB/min |
| PNG stack | 350 MB/min | 700 MB/min | — |
| MJPEG | 450 MB/min | 900 MB/min | 1.5 GB/min |
| H.264 | 35 MB/min | 70 MB/min | 120 MB/min |

Dashes mark combinations where encoding cannot keep up regardless of card speed.

!!! tip "Use the app's estimates, not this table"
    The ⓘ next to **Format** shows these numbers for your actual settings,
    against your card's measured speed and free space. This table is for
    planning before you are at the rig.

---

## Choosing

```
Does the analysis need colour?
├─ yes → Colour, and check headroom carefully
└─ no  → Greyscale (default)

How long is a recording?
├─ minutes    → MJPEG
├─ tens of mins → MJPEG at reduced fps, or H.264 if validated
└─ hours      → H.264, or timelapse image stack

Is per-frame fidelity critical (morphology, not just position)?
└─ yes → TIFF stack (low fps) or PNG stack (below ~15 fps)
```

---

## Format notes

### MJPEG — the default

Each frame is a JPEG. Quality is visually lossless at the settings used, files
are about ten times smaller than uncompressed, and every frame is independent.
Every tracking library reads it.

### TIFF stack

Uncompressed, exactly what the sensor produced. Enormous — at high framerates
it exceeds any SD card's write speed. Genuinely useful at low framerates where
fidelity matters more than volume.

### PNG stack

Lossless compression, roughly ten times smaller than TIFF. The catch is CPU:
PNG encoding is slow, and above roughly 15 fps the Pi cannot keep up regardless
of card speed. Ideal for timelapse.

### H.264 — the caveat

Hugely more efficient, hardware-accelerated, and produces the smallest files by
a wide margin. The compression artefacts land on moving subjects.

If storage forces H.264:

1. Record a short test clip of the actual behaviour
2. Run the real tracking pipeline on it
3. Compare against the same scene in MJPEG
4. Only then commit an experiment to it

For **reviewing footage by eye**, H.264 is fine and its size advantage is real.

---

## Image stacks versus video

**Video** is one file — easy to move, hard to inspect partially.

**Image stacks** are many files: easy to inspect, easy to process in parallel,
and a corrupt frame costs one frame rather than the tail of a file. But
thousands of small files are slow to copy over a network, and some filesystems
struggle above tens of thousands of entries in one directory.

For most tracking, MJPEG video is the better default. Use stacks when you need
per-frame access or maximum fidelity.
