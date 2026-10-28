# Recording overview

Everything on this page and the ones below it is for **running experiments**.
No terminal use, no Git, no Ansible.

---

## The short version

1. Power on the rig and its lights, put the arena in place
2. Open the **recorder app** on the rig's monitor
3. Check focus using the preview (++ctrl++ + scroll to zoom in)
4. Fill in the metadata, or load a list of planned sessions from a CSV
5. Choose resolution, framerate, color mode and format
6. Press **Start recording**
7. Press ++q++ or **Stop recording** when finished

The file name is built automatically from the metadata, so two recordings never
silently overwrite one another as long as their metadata differs.

---

## What gets saved

For a **video** recording, in your chosen save folder:

```
foraging_high-dim_1.avi              ← the footage
foraging_high-dim_1_metadata.yaml    ← everything about it
foraging_high-dim_1_frame_times.csv  ← when each frame was taken
```

For an **image stack**:

```
foraging_high-dim_1/
    foraging_high-dim_1_00001.tiff
    foraging_high-dim_1_00002.tiff
    ...
    metadata.yaml
    frame_times.csv
```

Frame numbers are 1-based and zero-padded to five digits, so they sort correctly
in any file browser or analysis script.

`frame_times.csv` lists each frame's number and `time_s`: when the sensor
exposed it, in seconds after the first frame. The video file only stores a
nominal frame rate, so use these times for any speed or duration analysis. A gap
of two frame intervals means one frame was missed; the metadata counts them
under `frames_missed`.

---

## The pages in this section

| Page | Read it when |
|---|---|
| [Before you start](before_you_start.md) | Setting up a rig for a session — focus, lighting, scale |
| [The recorder app](recorder_app.md) | Learning what each field does |
| [Metadata lists](metadata_lists.md) | You have many planned trials and little time between them |
| [Choosing settings](choosing_settings.md) | Deciding resolution, framerate and format for your experiment |
| [Troubleshooting](troubleshooting.md) | Something is not working |

---

!!! tip "The single most common mistake"
    Recording in **color** when grayscale would do. Grayscale files are about
    three times smaller for image stacks and roughly 2.5× smaller for MJPEG,
    and tracking algorithms work on brightness anyway. Use color only if the
    analysis actually needs hue — for example telling apart color-marked
    individuals.
