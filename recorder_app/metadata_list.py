"""
metadata_list.py
================
Loads a CSV of session metadata so the experimenter can step through
pre-planned recordings instead of typing fields between trials.

Column convention
-----------------
Four column names are reserved and map to fixed fields:

    experimenter, experiment, ant_id, trial

"ant_id" also accepts the headers antid, ant id, ant-id, id and individual.

EVERY OTHER COLUMN IS TREATED AS A TREATMENT. The column name becomes the
treatment name and the cell becomes its value. So a CSV like:

    experiment,ant_id,trial,density,light
    foraging,A01,1,high,dim
    foraging,A02,2,low,bright

produces two sessions, each with two treatments (density and light).

Column names are matched case-insensitively and stripped of surrounding
whitespace, since spreadsheet exports frequently carry both.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


# Columns that are NOT treatments
# Column names that map to fixed fields rather than becoming treatments.
# Aliases let spreadsheet headers vary without silently becoming treatments —
# "Ant ID" and "antid" are the same field as "ant_id".
RESERVED_COLUMNS = {"experimenter", "experiment", "ant_id", "trial"}

COLUMN_ALIASES = {
    "antid":       "ant_id",
    "ant id":      "ant_id",
    "ant-id":      "ant_id",
    "id":          "ant_id",
    "individual":  "ant_id",
}


# =============================================================================
# One row of the list
# =============================================================================

@dataclass
class MetadataRow:
    """One planned recording session."""
    experimenter: str = "NA"
    experiment:   str = "NA"
    ant_id:       str = "NA"
    trial:        str = "NA"
    treatments:   dict[str, str] = field(default_factory=dict)
    row_number:   int = 0

    def summary(self, max_length: int = 60) -> str:
        """Short one-line description for the dropdown."""
        treatment_part = ", ".join(f"{name}={value}"
                                   for name, value in self.treatments.items())
        parts = [
            self.experiment,
            f"ant {self.ant_id}" if self.ant_id not in ("", "NA") else "",
            treatment_part,
            f"trial {self.trial}",
        ]
        text  = "  ·  ".join(part for part in parts if part and part != "NA")
        if len(text) > max_length:
            text = text[:max_length - 1] + "…"
        return text or f"row {self.row_number}"


# =============================================================================
# Loading
# =============================================================================

def load_metadata_list(csv_file: Path) -> tuple[list[MetadataRow], list[str]]:
    """
    Read a metadata CSV.

    Returns (rows, warnings). Warnings describe recoverable problems
    (blank rows skipped, no treatment columns found) so the UI can surface
    them without failing the whole load.
    """
    warnings: list[str] = []
    rows:     list[MetadataRow] = []

    with csv_file.open("r", newline="", encoding="utf-8-sig") as file_handle:
        reader = csv.DictReader(file_handle)

        if not reader.fieldnames:
            raise ValueError("The file has no header row.")

        # Map normalised -> original column names so lookups are forgiving
        def normalise(name: str) -> str:
            key = (name or "").strip().lower()
            return COLUMN_ALIASES.get(key, key)

        column_map = {normalise(name): name for name in reader.fieldnames}
        treatment_columns = [
            original for normalised, original in column_map.items()
            if normalised not in RESERVED_COLUMNS and normalised
        ]

        if not treatment_columns:
            warnings.append(
                "No treatment columns found — every column matched a reserved "
                "name (experimenter, experiment, trial)."
            )

        for row_index, raw_row in enumerate(reader, start=1):
            # Skip entirely blank lines
            if not any((value or "").strip() for value in raw_row.values()):
                continue

            def cell(normalised_name: str) -> str:
                original = column_map.get(normalised_name)
                if original is None:
                    return "NA"
                return (raw_row.get(original) or "").strip() or "NA"

            treatments = {}
            for column in treatment_columns:
                value = (raw_row.get(column) or "").strip()
                if value:
                    treatments[column.strip()] = value

            rows.append(MetadataRow(
                experimenter = cell("experimenter"),
                experiment   = cell("experiment"),
                ant_id       = cell("ant_id"),
                trial        = cell("trial"),
                treatments   = treatments,
                row_number   = row_index,
            ))

    if not rows:
        raise ValueError("The file contains a header but no data rows.")

    return rows, warnings


# =============================================================================
# Filename generation
# =============================================================================

def build_auto_file_name(
    components: list[tuple[str, str, str]],
    include_treatment_names: bool = False,
) -> str:
    """
    Build the automatic file name from an ORDERED list of components.

    Each component is a (kind, name, value) tuple, where kind is either
    "field" (experiment, ant_id, trial) or "treatment". The order of the list
    is the order in the file name, so dragging a field in the UI changes the
    name directly.

    Joining rule: components are separated by "_", except that CONSECUTIVE
    treatments are joined with "-". This keeps names compact when treatments
    sit together (the usual case) while still allowing them to be interleaved
    with fields:

        experiment, ant_id, trial, density=high, light=dim
            -> foraging_A01_1_high-dim

        experiment, density=high, trial, light=dim
            -> foraging_high_1_dim

    With include_treatment_names, treatments are written as name-value:

            -> foraging_A01_1_density-high-light-dim

    Empty and "NA" values are skipped rather than appearing literally, and
    characters unsafe in file names are replaced.
    """
    def clean(text: str) -> str:
        text = (str(text) if text is not None else "").strip()
        if not text or text.upper() == "NA":
            return ""
        for character in '/\\:*?"<>|':
            text = text.replace(character, "_")
        return text.replace(" ", "-")

    # Render each component to a string, dropping empties
    rendered: list[tuple[str, str]] = []     # (kind, text)
    for kind, name, value in components:
        if kind == "treatment":
            clean_name, clean_value = clean(name), clean(value)
            if not clean_name or not clean_value:
                continue
            text = f"{clean_name}-{clean_value}" if include_treatment_names else clean_value
        else:
            text = clean(value)
            if not text:
                continue
        rendered.append((kind, text))

    # Join, merging runs of consecutive treatments with "-"
    parts: list[str] = []
    index = 0
    while index < len(rendered):
        kind, text = rendered[index]
        if kind != "treatment":
            parts.append(text)
            index += 1
            continue
        run = [text]
        index += 1
        while index < len(rendered) and rendered[index][0] == "treatment":
            run.append(rendered[index][1])
            index += 1
        parts.append("-".join(run))

    return "_".join(parts) or "recording"
