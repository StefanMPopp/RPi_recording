# Troubleshooting

Recording problems and their fixes. For setup and update problems see
[maintenance](../setup/maintenance.md).

---

## Nothing will come into focus

**Almost always the missing C–CS adapter ring.** The HQ camera body is CS-mount;
the 16 mm lens is C-mount. Without the 5 mm ring between them the entire focus
range sits behind the sensor.

Check for a thin metal ring between lens and body. If absent, fit one — they
cost a couple of euros and ship with most HQ cameras.

If the ring is fitted:

- Turn the focus ring slowly through its **entire** range; at 16 mm the sharp
  band is narrow
- Confirm you are turning the focus ring, not the aperture ring
- Zoom the preview in with ++ctrl++ + scroll — focus errors are invisible at
  full-frame preview size

---

## Frames are being dropped

The SD card cannot write as fast as the camera produces data. The warning panel
lists fixes in order of effectiveness; see
[write headroom](choosing_settings.md#write-headroom).

Quickest wins: greyscale, then lower framerate.

If drops appear at settings that used to work:

- The card may be nearly full — cards slow markedly above ~80% capacity
- The card may be ageing — run **Settings → Recalibrate write speed**
- The Pi may be hot and throttling — check ventilation

---

## The preview is black or frozen

1. Check the ribbon cable at both ends. It must be seated squarely with the
   contacts facing the right way
2. Restart the app
3. If still black, restart the Pi — the camera stack occasionally needs a clean
   start after an unclean shutdown

---

## Colours look wrong

If the preview shows a blue or orange cast, that is white balance responding to
the LED panels, not a fault. It does not affect greyscale recording at all.

If red and blue appear **swapped**, that is a software bug — report it with a
photo of the screen.

---

## The image is too dark or too bright

- Adjust the **aperture ring** on the lens
- Raise the LED brightness
- Lower the framerate — at lower framerates the sensor can expose each frame for
  longer, which brightens the image

Note the preview reflects the exposure your chosen framerate allows, so what you
see is what you will record.

---

## The file name is not what I expected

With **Name from metadata** ticked, the name comes from
`{experiment}_{treatments}_{trial}`. Parts that are empty or `NA` are omitted.
If the name looks short, a metadata field is probably still `NA`.

To type a name yourself, untick the box.

---

## It says the file already exists

Another recording with the same metadata was already made. Either:

- Change the **trial** number, or
- Confirm the overwrite if the earlier recording was a failed attempt

When using a metadata list, ✓ marks show which rows already have footage.

---

## Loading a profile does nothing

The file is probably not a profile. Recording metadata files
(`*_metadata.yaml`) and `config_app.yaml` have different structures and are
rejected with an explanation. Profiles are the files you created with
**Save profile…**.

---

## The app will not start

Run it from a terminal to see the error:

```bash
cd ~/RPi_recording
python3 recorder_app/main.py
```

Common causes:

| Message | Fix |
|---|---|
| `No module named 'PyQt6'` | `sudo apt install -y python3-pyqt6` |
| `No module named 'picamera2'` | `sudo apt install -y python3-picamera2` |
| `No module named 'cv2'` | `sudo apt install -y python3-opencv` |
| `No module named 'yaml'` | `pip install pyyaml --break-system-packages` |

If the error is something else, copy the whole traceback when reporting it.

---

## Recording stopped by itself

Either:

- **Duration** was set rather than *Record until stopped*
- The disk filled — check free space
- An error occurred, in which case a dialog explains it and the error is also
  written into the metadata file's `capture.error` field

---

## What to include when reporting a problem

1. Which rig
2. What you were doing
3. The exact error text, or a photo of the screen
4. The `_metadata.yaml` from the affected recording if there is one
5. Whether it happens on other rigs
