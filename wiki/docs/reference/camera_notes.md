# Camera notes

IMX477 and picamera2 behaviours that cost time to discover. Recorded here so
they cost it only once.

---

## The C–CS adapter ring

**The single most common hardware problem.**

The HQ camera body has a **CS-mount** throat. The 16 mm lens is **C-mount**.
The two differ by 5 mm of flange distance, and without the adapter ring the
lens's entire focus range sits behind the sensor plane. No amount of turning the
focus ring will help.

Symptom: everything is uniformly, unfixably blurred.

Fix: fit the 5 mm C–CS adapter ring between lens and body. They ship with most
HQ cameras and cost a couple of euros.

---

## Sensor modes: pixel count and field of view are independent

This is the subtle one, and it silently corrupts spatial calibration if ignored.

The IMX477 offers modes that differ in **two independent ways**:

1. How many pixels they output
2. **How much of the sensor they actually read**

| Mode | Sensor region read | Field of view |
|---|---|---|
| 4056 × 3040 | Full | 100% |
| 2028 × 1520 | Full, 2×2 binned | 100% |
| 2028 × 1080 | Vertical crop | 100% wide, ~71% tall |
| 1332 × 990 | Central 2664 × 1980 | **~66% wide** |

So `4056 × 3040` and `2028 × 1520` show **exactly the same scene** — one is
simply binned. But `1332 × 990` sees a genuinely smaller area.

### Why this matters for calibration

A naive implementation stores px/cm and recomputes it from the new pixel width
on a mode change. That is wrong:

- Full → binned: the scene is unchanged, so the physical frame width must stay
  the same while px/cm halves
- Full → cropped: the scene genuinely shrinks, so the physical frame width must
  shrink too

The app therefore stores **the scene width the full sensor would see**, and
derives px/cm and frame width from it for whichever mode is active. Modes with
reduced field of view are labelled `[NN% FoV]` in the dropdown, and
`fov_fraction_width` is written into every metadata file.

!!! warning "Practical consequence"
    With a 30 × 20 cm arena filling the frame, `1332 × 990` will **cut off the
    edges**. For high framerates with the whole arena in view, use
    `2028 × 1520` — full field of view, up to ~66 fps.

---

## Bit depth costs framerate

The sensor offers 8, 10 and 12-bit modes. Higher depth means lower maximum
framerate:

| Mode | 8-bit | 10-bit | 12-bit |
|---|---|---|---|
| 4056 × 3040 | 17.4 fps | 14.0 fps | 11.7 fps |

The app **exposes only 8-bit modes**, set by `ALLOWED_BIT_DEPTHS` in
`constants.py`. Tracking works on centroids and blobs; 8 bits is ample, and the
extra depth would cost framerate and storage for no benefit.

This also explains something confusing in the raw mode list: the same resolution
appears several times at different framerates. Those are the bit-depth variants.

If a future analysis genuinely needs more depth, change `ALLOWED_BIT_DEPTHS` —
the code handles it, the modes are simply filtered out of the UI.

!!! note "The '10 fps maximum' you may read online"
    Older documentation lists 10 fps as the maximum at full resolution. Current
    drivers reach 17.4 fps in 8-bit. The older figure refers to a single 12-bit
    mode.

---

## picamera2 constraints

### The lores stream must be YUV

picamera2 refuses `RGB888` on the `lores` stream:

```
RuntimeError: lores stream must be YUV
```

The preview therefore requests `YUV420` and converts. For greyscale it takes the
Y plane directly — cheaper, and it avoids colour-conversion bugs entirely.

### YUV plane order

OpenCV's `COLOR_YUV2RGB_I420` matches picamera2's layout. `YV12` swaps U and V.
If colours ever come back with red and blue exchanged, that is the constant to
check.

### Changing sensor mode requires a restart

Setting a mode does not affect a running stream. The camera must be stopped,
reconfigured and restarted. `PiCamera.set_mode()` handles this, restarting the
preview automatically if one is active.

### The preview stream must match the frame's aspect ratio

A fixed 16:9 preview against a 4:3 sensor mode crops the image before it ever
reaches the display. The preview height is therefore derived from the active
mode. Both dimensions must be even — YUV420 requires it.

### Framerate affects exposure

Setting `FrameRate` also constrains exposure time. At low framerates the sensor
can expose longer, so the image brightens. This is why the preview applies the
recording framerate: what you see reflects what you will record.

---

## Camera not detected

```bash
libcamera-hello --list-cameras
```

If the IMX477 is absent:

1. Check the ribbon cable at **both** ends — contacts facing the right way,
   connector fully seated and latched
2. Reboot — the camera stack sometimes needs a clean start after an unclean
   shutdown
3. Try a known-good cable; ribbon cables fail more often than cameras

---

## Useful diagnostic commands

| Purpose | Command |
|---|---|
| List cameras and modes | `libcamera-hello --list-cameras` |
| Quick preview test | `libcamera-hello -t 5000` |
| Capture a still | `libcamera-still -o test.jpg` |
| Temperature | `vcgencmd measure_temp` |
| Throttling history | `vcgencmd get_throttled` |

`get_throttled` returning anything other than `0x0` means the Pi has been
throttled at some point — worth checking when a rig drops frames at settings
that work elsewhere.
