# Recording overview

This section covers everything needed to run a recording session using the
**Recorder app** — a lightweight interface accessible from any browser on the same network
as the recording Pis.

---

## The Recorder app

Each deployed Pi runs the Recorder app automatically on boot. You do not need to install,
update, or configure it — that is handled by the Manager app.

To access a rig's Recorder app, open a browser on your analysis machine and go to:

```
http://pi1.local:8080   # replace pi1 with the hostname of the rig you want
```

!!! note
    Your analysis machine must be on the same Wi-Fi or ethernet network as the Pis.

---

## What the Recorder app does

1. Accepts recording parameters (arena dimensions, species, experimenter, etc.)
2. Starts and stops the camera recording
3. Saves video files to a timestamped folder on the Pi
4. Transfers completed recordings to your analysis machine

---

## Before your first session

- Confirm the Pi is powered on and the LED panels are running
- Check the camera view and focus in the Recorder app's live preview
- Fill in the experiment config for this session

→ See [Run a recording session](record.md) for the full walkthrough.
