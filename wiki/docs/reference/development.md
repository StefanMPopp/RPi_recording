# Working on the code

---

## The loop

```bash
cd ~/RPi_recording
# edit
python3 recorder_app/main.py        # test
git add .
git commit -m "what changed"
git push
cd ansible && ansible-playbook -i inventory.ini update.yml
```

Always on the dev Pi. Never on a recording Pi.

---

## Conventions

These are followed throughout; keeping to them keeps the code readable by the
next person.

**Paths** — always `pathlib.Path`, never `os.path`.

**Names** — explicit over short. `mean_velocity`, not `mv`. Directory variables
end `_dir`, file paths end `_file`, DataFrames end `_df`.

**Functions** — wrap in a function when something is called more than once.
Avoid classes unless they earn their place: `RecordingSession` holds genuine
state across threads, which justifies it; a class wrapping two pure functions
does not.

**Section dividers** — `=` for major breaks, `-` for minor:

```python
# =============================================================================
# Major section
# =============================================================================

# ── Minor section ────────────────────────────────────────────────────────────
```

**Config** — no hardcoded paths, parameters or thresholds. They go in
`constants.py` or a YAML file.

**Comments** — explain *why*, not *what*. The code says what it does; the
comment should say why it does it that way, especially where the reason is
non-obvious.

---

## Testing off the Pi

The camera stub means everything except live capture runs on any machine:

```bash
pip install PyQt6 numpy pyyaml opencv-python
python3 recorder_app/main.py
```

`make_camera()` returns a `StubCamera` when picamera2 is unavailable, producing
synthetic frames and mirroring the real IMX477 mode list including crop
geometry. UI work, metadata handling, profiles and CSV lists can all be
developed and tested this way.

**Live capture, focus, and real timing must be tested on a Pi.** The stub cannot
tell you whether the SD card keeps up.

---

## Adding a dependency

=== "Python package (pip)"
    ```bash
    pip install PACKAGE --break-system-packages
    pip freeze > recorder_app/requirements.txt
    git add recorder_app/requirements.txt
    git commit -m "add PACKAGE"
    git push
    cd ansible && ansible-playbook -i inventory.ini update.yml
    ```

    `update.yml` installs from `requirements.txt`, so this reaches every rig.

=== "System package (apt)"
    ```bash
    sudo apt install -y PACKAGE
    ```

    Then add it to the apt task in `ansible/bootstrap.yml`, and run **bootstrap**
    rather than update:

    ```bash
    ansible-playbook -i inventory.ini bootstrap.yml
    ```

    `update.yml` deliberately does not install system packages — that keeps
    routine updates fast.

!!! warning "picamera2, PyQt6 and opencv come from apt, not pip"
    They are excluded from `requirements.txt` on purpose. `picamera2` needs
    system libraries pip cannot supply; the other two have prebuilt ARM packages
    that avoid a very long compile. Do not add them to `requirements.txt` — pip
    would try to build them from source on every rig.

---

## Adding a feature

Follow the existing seams.

### A new output format

1. `constants.py` → add to `OUTPUT_FORMATS`
2. `record.py` → a writer class with `write(frame, index)` and `close()`,
   and a branch in `make_writer()`
3. `benchmark.py` → an entry in `_FORMAT_WRITE_RATES_MBS` and
   `_GREYSCALE_FACTORS`
4. `main_window.py` → a short description in the tooltip table

### A new metadata field

1. `main_window.py` → the widget, in `_build_metadata_group`
2. `main_window.py` → include it in `_collect_recording_settings`
3. `metadata.py` → add it to `build_metadata()`
4. `main_window.py` → **both** `_collect_profile_from_ui` **and**
   `_apply_profile_to_ui`

Step 4 is the one people miss. Save and load are a matched pair; adding to one
alone gives a setting that silently fails to restore.

### A new camera control

1. `camera.py` → a method on **both** `PiCamera` and `StubCamera`
2. `main_window.py` → the widget and its handler
3. Decide whether it needs a stream restart (like sensor mode) or applies live
   (like framerate)

Keeping the stub's interface identical is what keeps off-Pi development
possible.

---

## Testing before pushing

There is no automated test suite; the app is UI-heavy and hardware-bound. Before
pushing, check by hand:

- [ ] The app starts
- [ ] The preview runs; zoom and pan behave
- [ ] Every sensor mode selects without error
- [ ] A short recording works in MJPEG **and** one image stack format
- [ ] The metadata file appears and contains what it should
- [ ] Save then load a profile — everything restores
- [ ] Load `example_metadata_list.csv` and step through it

Logic that is not UI-bound *can* be tested directly, and is worth it for
anything with real branching — CSV parsing, file naming, headroom maths:

```bash
python3 -c "
from metadata_list import build_auto_file_name
print(build_auto_file_name('foraging', {'density':'high'}, '1'))
"
```

---

## Debugging

Run from a terminal to see tracebacks:

```bash
python3 recorder_app/main.py
```

| Symptom | Look at |
|---|---|
| Camera errors | `libcamera-hello --list-cameras`, ribbon cable |
| Dropped frames | Queue depth in the status panel; write speed calibration |
| UI freezes | Work being done on the Qt main thread instead of a worker |
| Colours wrong | The YUV conversion constant in `camera.py` |
| Profile does not restore | A field added to `_collect_` but not `_apply_` |

!!! danger "Never touch widgets from a worker thread"
    Qt will crash, usually later and somewhere unrelated. Frames cross into the
    UI thread by signal (`frame_ready`). Any new cross-thread communication must
    do the same.
