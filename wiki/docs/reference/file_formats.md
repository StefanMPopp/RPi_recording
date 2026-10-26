# File formats

Why the four formats exist, what they cost, and which to use.

---

## The tracking constraint

Video codecs fall into two families, and the difference matters more for
tracking than for viewing.

**Intra-frame** (MJPEG, TIFF, PNG) compresses each frame independently. Every
frame stands alone, decodes identically however you seek to it, and contains no
information borrowed from its neighbors.

**Inter-frame** (H.264) stores occasional full frames and describes the rest as
*differences*. This is dramatically more efficient — and it concentrates its
errors precisely where things move.

For a tracker, that is the worst possible place to put an artifact. The moving
animal is both the thing being measured and the thing the codec approximates
most aggressively. Blocking artifacts around a moving subject shift the apparent
centroid, and the error correlates with speed, which is often the variable of
interest.

**Hence the default is MJPEG**, despite files roughly ten times larger than
H.264.

---

## The four formats

| Format | Compression | Independent frames | Tracking |
|---|---|---|---|
| **MJPEG (.avi)** | Lossy, per frame | ✓ | Recommended |
| **TIFF stack** | None by default, or LZW / deflate | ✓ | Ideal, large |
| **PNG stack** | None by default, or lossless compressed | ✓ | Ideal, large |
| **H.264 (.mp4)** | Lossy, inter-frame | ✗ | Use with care |

---

## Size estimates

Approximate, static scene, **grayscale**. Color is roughly 2.5–3× more.

### 2028 × 1520 (recommended for a full-arena view)

| Format | 15 fps | 30 fps | 60 fps |
|---|---|---|---|
| TIFF stack (uncompressed) | 2.8 GB/min | 5.5 GB/min | 11.1 GB/min |
| PNG stack | 1.9 GB/min | 3.7 GB/min | — |
| MJPEG | 340 MB/min | 680 MB/min | 1.4 GB/min |
| H.264 | 25 MB/min | 50 MB/min | 100 MB/min |

### 4056 × 3040 (full resolution)

| Format | 5 fps | 10 fps | 17 fps |
|---|---|---|---|
| TIFF stack (uncompressed) | 3.7 GB/min | 7.4 GB/min | 12.6 GB/min |
| PNG stack | 2.5 GB/min | 4.9 GB/min | — |
| MJPEG | 450 MB/min | 900 MB/min | 1.5 GB/min |
| H.264 | 35 MB/min | 70 MB/min | 120 MB/min |

Dashes mark combinations where encoding cannot keep up regardless of card speed.

!!! note "How firm these numbers are"
    The **TIFF** rows are exact for uncompressed files (width × height × fps).
    The **PNG** rows assume about two-thirds of the raw size, which was
    measured on noisy test frames — cleaner footage compresses better, so
    treat them as an upper bound. The **MJPEG** and **H.264** rows are
    estimates that have not been checked against real recordings.

!!! tip "Use the app's estimates, not this table"
    The ⓘ next to **Format** shows these numbers for your actual settings,
    against your card's measured speed and free space. This table is for
    planning before you are at the rig.

---

## Choosing

```
Does the analysis need color?
├─ yes → Color, and measure the maximum fps first
└─ no  → Grayscale (default)

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

Lossless. The app writes TIFFs **uncompressed** by default
(`TIFF_COMPRESSION = "none"` in `constants.py`), because the priority is frame
rate. OpenCV's own default would be LZW — about 15% smaller on typical footage
but roughly ten times slower to write (measured ~207 ms against ~20 ms per 4K
grayscale frame). `"lzw"` and `"deflate"` are available when file size matters
more.

Which setting records faster depends on what limits the rig. At 4K grayscale a
frame is 12.3 MB, so a card sustaining 90 MB/s caps uncompressed stacks near
7 fps however fast the encoder is — while compressing spends CPU the Pi has
little of. Use **Settings → Measure maximum fps** after changing it.

### PNG stack

Lossless, typically around two-thirds of the raw size (it varies with image
content). OpenCV's default PNG settings are already tuned for speed, so leave
`PNG_COMPRESSION_LEVEL` unset: setting a level on its own measured about 2.5×
*slower*, because it discards the fast filter and strategy OpenCV otherwise
uses.

By default the app writes **uncompressed** PNGs (`PNG_MODE = "store"`), still
normal lossless PNGs that every tool opens, about 4× faster to encode than
OpenCV's compressed default and about 50% larger. Uncompressed PNG needs a
recent OpenCV; on older builds it quietly falls back to the compressed default.
Set `PNG_MODE = "default"` to favor file size.

On a Pi 4 at 4K grayscale, compressed PNG measured about 4–5 fps.

### H.264 — the caveat

Hugely more efficient, and produces the smallest files by a wide margin. The
compression artifacts land on moving subjects.

Hardware-accelerated only at **1080p and below**: the Pi 4's encoder cannot
handle more, and above that the app uses a software encoder that is *slower*
than MJPEG. Even at 1080p it is used only if a streaming test passes first;
the Format ⓘ tooltip states which encoder you will get.

If storage forces H.264:

1. Record a short test clip of the actual behavior
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
