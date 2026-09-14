# Before you start

Five minutes of setup before the first recording of a session saves re-running
trials later. Focus and scale in particular cannot be fixed after the fact.

---

## 1. Physical setup

- Power on the Pi and wait for the desktop (about 30 seconds)
- Switch on the LED panels and let them warm up for a minute — output drifts
  slightly for the first minute from cold, which shows up as a brightness
  gradient across a long recording
- Place the arena and check nothing casts a shadow across it
- Check the lens is clean

---

## 2. Focus

Focus is set on the lens, not in software.

1. Open the recorder app — the preview starts automatically
2. Put something with fine detail in the arena at the height the animals will
   be (a ruler or printed text works well)
3. Hold ++ctrl++ and scroll on the preview to zoom in on it
4. Turn the **focus ring** on the lens until the detail is sharp
5. Double-click the preview to zoom back out

!!! warning "If nothing will come into focus"
    Check that the **C–CS adapter ring** is fitted between the lens and the
    camera body. Without it, the whole focus range sits behind the sensor.
    See the [camera notes](../reference/camera_notes.md) for detail.

The lens also has an **aperture ring**. Opening it wider gives a brighter image
but a shallower depth of field, so animals at different heights go soft. With
LED panels you rarely need it wide open.

---

## 3. Scale

The scale converts pixels to centimetres for the analysis. **Set it now** — it
is easy to forget and impossible to recover later without re-measuring the rig.

In the **Metadata** section, choose which value you want to type:

=== "Frame width (usually easier)"
    Lay a ruler across the full width of the frame and read off how many
    centimetres are visible edge to edge. Select **frame width** and type it.
    The app computes px/cm.

=== "px/cm"
    If you already know the scale, select **px/cm** and type it directly.
    The app computes the frame width.

Whichever you type, the other is filled in automatically and both are saved to
the metadata.

!!! info "Why the scale changes when you change sensor mode"
    Changing resolution changes how many pixels span the frame, so px/cm changes
    even though the physical scene has not moved. The app recalculates this
    automatically and correctly, including for cropped modes that see less of
    the scene. You only need to measure once.

---

## 4. A test recording

Before the first real trial, record 10 seconds and check:

- The footage opens and looks as expected
- **Frames dropped** was 0, or a fraction of a percent
- The metadata file sits next to the footage and contains what you expect

If frames are being dropped, fix it now rather than losing a real trial — see
[choosing settings](choosing_settings.md#write-headroom).

---

## Quick checklist

- [ ] Lights on and warmed up
- [ ] Arena placed, no shadows
- [ ] Focus checked with the preview zoomed in
- [ ] Scale entered
- [ ] Save folder correct
- [ ] Metadata filled in, or a list loaded
- [ ] Test recording shows no dropped frames
