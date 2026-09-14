# Repository layout

```
RPi_recording/
├── recorder_app/                 the recording application
│   ├── main.py                   entry point
│   ├── main_window.py            all UI
│   ├── camera.py                 picamera2 wrapper + stub
│   ├── record.py                 capture engine, writers
│   ├── metadata.py               metadata sidecar
│   ├── metadata_list.py          CSV lists, auto file naming
│   ├── benchmark.py              write speed, headroom
│   ├── config.py                 YAML load/save
│   ├── constants.py              all tuneable values
│   ├── requirements.txt          pip dependencies only
│   └── example_metadata_list.csv
│
├── ansible/                      fleet management
│   ├── inventory.ini             which Pis exist, and where
│   ├── bootstrap.yml             set up a Pi from scratch
│   ├── update.yml                pull latest code onto all Pis
│   └── host_vars/
│       ├── template.yml          committed
│       └── piN.yml               NOT committed — per-rig values
│
├── wiki/                         this documentation
│   ├── mkdocs.yml
│   └── docs/
│
├── .gitignore
├── LICENSE
└── README.md                     one-liner pointing at the wiki
```

---

## Deliberately not committed

Listed in `.gitignore`:

| Pattern | Why |
|---|---|
| `ansible/host_vars/*.yml` | Per-rig hardware values; differ by machine |
| `config_app.yaml` | Contains the write-speed calibration for *that* SD card |
| `__pycache__/`, `*.pyc` | Generated |
| `.venv/` | Environment, not code |
| `*.avi`, `*.mp4`, `*.tiff`, `*.png` | Recordings — far too large for Git |
| `site/` | MkDocs build output |

!!! warning "config_app.yaml must stay uncommitted"
    It holds a write speed measured on one specific SD card. Sharing it across
    rigs would give every Pi wrong headroom estimates, and the wrongness would
    be invisible until frames started dropping.

---

## Branches

| Branch | Contents |
|---|---|
| `main` | Source of truth. Everything above. |
| `gh-pages` | Generated HTML from `mkdocs gh-deploy`. **Never edit or merge.** |

`gh-pages` is managed entirely by MkDocs. Merging it into `main` would put built
HTML into the source tree.

---

## The three config layers

Deliberately separate, because they change at different rates and for different
reasons:

| File | Scope | Committed? | Changes when |
|---|---|---|---|
| `constants.py` | Whole project | ✓ | A developer changes a default |
| `ansible/host_vars/piN.yml` | One rig | ✗ | A rig's hardware changes |
| `config_app.yaml` | One rig, app-managed | ✗ | Write speed is recalibrated |
| session profile `.yaml` | One experiment | user's choice | The experimenter saves one |

Merging these would mean either committing machine-specific values or hardcoding
things that must vary.
