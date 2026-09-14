# Metadata lists

If you have many planned trials and little time between them, you can prepare
the metadata in a spreadsheet beforehand and step through it during the session
with a single key press.

---

## The column convention

Save your plan as **CSV**. The header row defines the fields.

!!! info "Three reserved column names"
    `experimenter`, `experiment`, `trial`

    **Every other column is treated as a treatment.** The column name becomes
    the treatment name, and the cell becomes its value.

So this file:

```csv
experimenter,experiment,trial,density,light
SP,foraging,1,high,dim
SP,foraging,2,high,bright
SP,foraging,3,low,dim
SP,foraging,4,low,bright
```

gives four sessions, each with a `density` and a `light` treatment. No prefix or
special naming is needed — just name the column after the treatment.

Column names are matched case-insensitively and surrounding whitespace is
ignored, so exports from Excel or LibreOffice work without cleaning up.

---

## Using a list

1. In the **Metadata** section, click **Load metadata from file…**
2. Choose your CSV
3. A navigation bar appears: `◀  [dropdown]  ▶  ✕`

| Control | Action |
|---|---|
| ◀ / ▶ | Previous / next row |
| ++left++ / ++right++ | Same, when not typing in a field |
| dropdown | Jump to any row |
| ✕ | Close the list and return to manual entry |

Selecting a row fills in the metadata fields and updates the file name.
**Fields stay editable** — you can adjust anything on the fly without changing
the file.

---

## Automatic advance

When a recording finishes successfully, the list moves to the next row on its
own. In practice a session looks like:

1. Start recording → wait → ++q++
2. The next trial's metadata is already loaded
3. Start recording again

You are told when you reach the end of the list.

---

## The ✓ marks

Rows whose output file already exists are marked with a **✓** in the dropdown,
so you can see at a glance which sessions still need recording. This survives
closing and reopening the app, because it checks the actual files rather than
remembering what you did.

The marks refresh when you change the save folder, the format, or the naming
style. They require **Name from metadata** to be ticked — without it there is no
way to know which file a row would produce.

---

## Worked example

A 2×2 design with four replicates — sixteen recordings:

```csv
experimenter,experiment,trial,density,light
SP,foraging,1,high,dim
SP,foraging,1,high,bright
SP,foraging,1,low,dim
SP,foraging,1,low,bright
SP,foraging,2,high,dim
SP,foraging,2,high,bright
SP,foraging,2,low,dim
SP,foraging,2,low,bright
```

produces files named:

```
foraging_high-dim_1.avi
foraging_high-bright_1.avi
foraging_low-dim_1.avi
foraging_low-bright_1.avi
foraging_high-dim_2.avi
...
```

Every name is unique, so nothing overwrites anything.

!!! warning "Check for name collisions before a long session"
    If two rows would produce the same file name, the second recording will
    prompt to overwrite the first. Make sure `trial` (or some other column)
    differs between otherwise-identical rows.

---

## Tips

- Keep the CSV in the same folder as the recordings — it documents the session
- An `example_metadata_list.csv` ships with the app to copy from
- Rows can be added mid-session: edit the CSV, then reload it
- Blank lines are skipped, so you can space out blocks for readability
