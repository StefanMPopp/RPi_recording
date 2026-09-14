# Recorder app architecture

---

## Modules

| Module | Responsibility |
|---|---|
| `main.py` | Entry point. Creates the Qt application and window. |
| `main_window.py` | All UI: widgets, layout, event handlers. |
| `camera.py` | Wraps picamera2. Enumerates sensor modes, runs the preview, captures frames. Falls back to a stub off-Pi. |
| `record.py` | The capture engine: threads, queue, per-format writers. |
| `metadata.py` | Builds and writes the metadata sidecar. |
| `metadata_list.py` | Reads metadata CSVs; builds automatic file names. |
| `benchmark.py` | Measures write speed; estimates data rates and headroom. |
| `config.py` | YAML load/save for app config and profiles. |
| `constants.py` | Every tuneable value in one place. |

Dependencies run one way: `main_window` imports the others; they do not import
it. Everything except `main_window` is testable without Qt.

---

## Threading

Three threads:

```
Qt main thread          UI, event handling, status updates
  │
  ├── preview thread    grabs low-res frames  → Qt signal → preview widget
  │
  └── during recording:
        capture thread  full-res frames → bounded queue
        writer thread   queue → disk
```

### Why capture and writing are separate

A single loop doing both would stall capture whenever the SD card paused,
distorting the frame timing of everything after it. With a queue between them:

- The capture thread keeps precise timing
- Disk stalls consume queue slack instead of disrupting capture
- **A full queue is an unambiguous "the disk cannot keep up" signal** — which is
  what gives an honest dropped-frame count rather than an estimate

Queue depth is surfaced live in the status panel because it is the earliest
warning of trouble, appearing before any frame is actually lost.

### Thread safety

Frames cross from the preview thread to the UI thread by Qt signal
(`frame_ready`), which marshals them safely. Touching widgets directly from a
non-Qt thread will eventually crash.

---

## Data flow for one recording

```
UI form
  └─► RecordingSettings          derives every output path
        └─► RecordingSession
              ├─ capture thread ──► queue ──► writer thread ──► disk
              └─ stop() ──► summary dict
                              └─► build_metadata() ──► YAML sidecar
```

`RecordingSettings` is the single place where paths are decided. Both
`record.py` and `metadata.py` derive from it, so the video and its sidecar can
never disagree about where they live.

---

## Naming convention

Output paths follow the user's convention — **no dates in file names**, since
dates live in the metadata:

=== "Video"
    ```
    {save_dir}/{file_name}.avi
    {save_dir}/{file_name}_metadata.yaml
    ```

=== "Image stack"
    ```
    {save_dir}/{file_name}/
        {file_name}_00001.tiff
        {file_name}_00002.tiff
        metadata.yaml
    ```

Frame counters are 1-based, zero-padded to five digits.

Automatic names are `{experiment}_{treatments}_{trial}`, built in
`metadata_list.build_auto_file_name()`. Empty and `NA` parts are dropped;
filesystem-unsafe characters are replaced.

---

## The camera stub

`camera.py` exports `make_camera()`, returning a real `PiCamera` when picamera2
is importable and a `StubCamera` otherwise. The stub produces synthetic frames
and mirrors the real IMX477 mode list including crop geometry.

This lets the entire UI be developed and tested on a laptop. Keep the two
classes' interfaces identical when adding methods, or the stub silently stops
being a valid substitute.

---

## Write speed and headroom

`benchmark.py` measures sustained write speed by writing a 400 MB file — large
enough to defeat the burst cache and reflect real sustained performance.

Headroom is then estimated rather than measured:

```
write_rate  = base_rate × pixel_scale × fps_scale × greyscale_factor
headroom    = 1 − (write_rate ÷ (measured_speed × 0.85))
```

The 0.85 is a safety margin for variance. `base_rate` values in
`_FORMAT_WRITE_RATES_MBS` are empirical for the IMX477 on a static scene; they
are estimates, deliberately conservative, and only ever used to guide a choice —
never to gate a recording.

---

## Extension points

| To add… | Change |
|---|---|
| An output format | `OUTPUT_FORMATS` in `constants.py`, a writer in `record.py`, a rate in `benchmark.py` |
| A metadata field | The UI in `_build_metadata_group`, then `build_metadata()` |
| A camera control | `camera.py`, exposed via a UI control |
| A profile setting | `_collect_profile_from_ui` and `_apply_profile_to_ui`, both in `main_window.py` |

Profile save and load are a matched pair. Adding to one without the other gives
a setting that silently fails to restore — an easy bug to introduce and an
irritating one to find.
