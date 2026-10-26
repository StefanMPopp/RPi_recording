# The recorder app

A reference for every control in the app. Fields are grouped exactly as they
appear on screen.

The window has the live preview on the left and the controls on the right.
When a recording starts, the controls are replaced by a live status panel.

---

## Live preview

| Action | Result |
|---|---|
| ++ctrl++ + scroll | Zoom in and out, centerd on the cursor |
| scroll | Pan up and down (when zoomed in) |
| ++shift++ + scroll | Pan left and right (when zoomed in) |
| double-click | Reset to the full frame |

The current zoom level is shown at the top right of the preview, with a
**Reset view** button next to it while zoomed.

The preview is a lower-resolution stream than the recording — it exists to
check framing and focus, not to judge final image quality. Zoom does not affect
what is recorded; the full frame is always captured.

---

## Camera

**Sensor mode** — the resolution. Some modes are marked `[66% FoV]`, meaning
they read only part of the sensor and therefore see a **physically smaller
area**, not just a smaller image. See
[choosing settings](choosing_settings.md#sensor-modes-and-field-of-view).

**Framerate** — any value up to the mode's maximum, shown as `max NN.N` beside
the field. Lower framerates are the simplest way to reduce data rate without
losing resolution, and are ideal for slow behaviors or long recordings.

**Color** — Grayscale (default) or Color. Grayscale records only the
brightness channel: about 3× smaller for image stacks, 2.5× for MJPEG, and no
loss for tracking purposes.

**Show preview** — untick if the Pi struggles. Displaying the preview costs
some CPU; disabling it frees that for encoding.

---

## Output

**Save to** — the output folder. The folder icon opens a browser.

**Format** — the file format. Hover the blue ⓘ for the measured capacity table:
for every format at the current resolution and color mode, the maximum frame
rate, what limits it (camera, encoding or SD card), megabytes per frame, and how
long a recording fits on the card. Empty until you run
**Settings → Measure maximum fps**. See
[maximum frame rate](choosing_settings.md#maximum-frame-rate).

The line below the selector summarizes the chosen format — its maximum and how
long fits on the card — and turns red if the selected frame rate is above that
maximum.

**Name from metadata** — when ticked (the default), the file name is built
automatically as:

```
{experiment}_{treatments}_{trial}
```

so `foraging` + `density=high, light=dim` + trial `1` becomes
`foraging_high-dim_1`. Empty or `NA` parts are left out. Untick to type a name
yourself.

Whether treatment *names* appear alongside their values is set under
**Settings → Include treatment names in file name**:

| Setting | Result |
|---|---|
| Off (default) | `foraging_high-dim_1` |
| On | `foraging_density-high-light-dim_1` |

**File name** — the name without extension. Read-only while auto-naming is on.
For image stacks it is also the name of the folder the images go into.

**Duration** — tick **Record until stopped** to end manually, or untick and set
a number of seconds for the recording to stop itself.

---

## Metadata

Everything here is written to the metadata file beside the footage.

**Load metadata from file…** — load a CSV of planned sessions and step through
it. See [metadata lists](metadata_lists.md).

**Experimenter, Experiment, Trial** — free text. `Experiment` and `Trial` feed
the automatic file name; `Experimenter` does not.

**Treatments** — as many named treatments as the experiment needs. Press
**+ Add treatment** for another, **✕** to remove one. Each has a name
(e.g. `density`) and a value (e.g. `high`). Rows where either field is blank
are ignored.

**Scale** — see [before you start](before_you_start.md#3-scale).

---

## Profile

**Save profile…** / **Load profile…** stores every setting on this page —
camera, output, metadata, scale — as a `.yaml` file you can reload later. Useful
for switching between experiment types without re-entering everything.

!!! note "Profiles are not metadata files"
    Loading a recording's `_metadata.yaml` as a profile will be refused with an
    explanation. They have different structures on purpose: a profile describes
    what you are *about* to record, a metadata file describes what *was*
    recorded.

---

## While recording

The controls are replaced by a live status panel:

| Field | Meaning |
|---|---|
| **Elapsed** | Time since the recording started |
| **Frames written** | Frames successfully saved to disk |
| **Dropped frames** | Frames lost because the disk could not keep up, with percentage |
| **Queue** | How full the write buffer is — the live warning sign |

**Queue** is the most useful number to watch. It should hover near 0%. If it
climbs steadily, the disk is falling behind and drops will follow.

If frames are dropped, a warning appears listing the most effective fixes in
order. Stop, change the setting, and start again — the trial is usually still
salvageable if you notice early.

Press ++q++ or click **Stop recording** to finish.

---

## Menus

**File → Load profile / Save profile** — same as the buttons.

**Settings → Measure maximum fps for current settings** — records each format
flat out for a few seconds (about 25 s in total) and fills the capacity table
for the current resolution and color mode. Test footage goes to a hidden folder
in the save directory and is deleted.

**Settings → Recalibrate write speed** — measures the SD card's sustained write
speed by writing a 400 MB test file and forcing it onto the card, taking 10–20
seconds. Run it when using a new card. The first fps measurement runs it
automatically if it has never been done. The result is stored per Pi.

**Settings → Include treatment names in file name** — the naming style toggle
described above.
