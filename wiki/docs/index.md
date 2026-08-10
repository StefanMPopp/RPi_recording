# RPi Recording — Field Guide

This guide covers everything needed to set up, maintain, and use the insect video recording rigs.

---

## How this guide is organised

The rigs are managed through **two separate apps**, each with a different audience and purpose.

=== "Manager app"
    **Who uses it:** the person responsible for the rigs (you).

    **What it does:** installs software on new Pis, updates all Pis when the code changes,
    and handles all maintenance tasks.

    **Where it runs:** on the dev Pi only. Day-to-day users never need to open it.

    → See [Setup & maintenance](setup/overview.md)

=== "Recorder app"
    **Who uses it:** anyone running an experiment.

    **What it does:** configures recording parameters, starts and stops recordings,
    and transfers data to the analysis machine.

    **Where it runs:** on each deployed Pi, accessible from any browser on the same network.

    → See [Recording](recording/overview.md)

---

## Hardware overview

Each rig consists of:

- Raspberry Pi 4
- HQ camera module with 16 mm lens
- LED panels on an aluminium extrusion frame
- ~30 × 20 cm recording arena

Eight identical rigs are deployed. One additional Pi serves as the **dev Pi** — it runs the
Manager app and is the only machine used for software development and maintenance.
