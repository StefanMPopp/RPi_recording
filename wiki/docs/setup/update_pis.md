# Step 3: Update Pis

Whenever the recording software changes, all Pis need to receive the update. This is done
from the Manager app on the dev Pi with a single button press.

---

## When to update

- A bug has been fixed
- A new feature has been added to the recorder app
- A Python package has been added or its version has changed

The Pis do not update themselves — updates only happen when you trigger them.

---

## How it works

Updates follow a fixed sequence:

1. New code is written and tested on the dev Pi
2. The changes are committed and pushed to GitHub by the developer
3. The Manager app's **Update all Pis** button pulls those changes onto every Pi

```
Developer pushes code → GitHub → Manager app pulls → all Pis updated simultaneously
```

Only step 3 is relevant here. Steps 1 and 2 are the developer's responsibility.

---

## Run an update

!!! warning "Dev Pi action"
    Updates are triggered from the **dev Pi only**, via the Manager app.
    Recording Pis only need to be powered on and connected to the network — no input
    is needed on them.

1. Ensure all Pis are powered on and on the network.
2. Open the **Manager app** on the dev Pi.
3. Click **Update all Pis**.

The app connects to each Pi, pulls the latest code from GitHub, and syncs any new
dependencies. Only what has changed is transferred — the entire repository is not
re-downloaded each time.

To update a single Pi (e.g. after adding it mid-project):

1. Open the Manager app.
2. Click **Update** next to the specific Pi.

---

## If something goes wrong

The Manager app shows which Pi failed and the error message from Ansible. Common causes:

| Symptom | Likely cause | Fix |
|---|---|---|
| Pi does not respond | Pi is off or not on the network | Power it on, wait 60 s, retry |
| Task fails on all Pis | Error in the new code or requirements | Fix on dev Pi, push, retry |
| Task fails on one Pi | Network or disk issue on that Pi | SSH into it and inspect manually |

If a Pi is in a broken state after a failed update, you can re-run the full bootstrap
from the Manager app — it is safe to run on a Pi that already has software installed.
