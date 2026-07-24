# Firebird minimal post-processing v1

This is a separate, review-first replacement prototype. It does not import or
call the legacy post-processing scripts.

## Standalone repository

The independent Git repository is:

`/Users/New/Library/CloudStorage/Dropbox/Projects/Coding_Repositories/IDtracker_postprocessing_prototype`

It has its own `VERSION`, `CHANGELOG.md`, commits, and version tags. It is not
part of `One_script_to_rule_them_all` and does not import or modify that
pipeline.

The installer places the Firebird copy in:

`~/idtracker_postprocessing_v1`

## Install on both machines

In Finder, open the development folder and double-click:

`install_both.command`

The installer:

1. creates `venv-mac` only when absent, otherwise reuses it;
2. checks that the Mac Python has Tkinter;
3. installs only missing Mac packages: tomlkit, NumPy, h5py, and Matplotlib;
4. asks for the Firebird SSH host and private key;
5. copies the processor and documentation to Firebird;
6. creates the dedicated `idtracker_reprocess_v1` Conda environment on Firebird
   if it does not already exist;
7. installs only missing Firebird packages and verifies Python 3.11, NumPy,
   h5py, and Matplotlib there.

Ordinary code changes do not recreate either environment or reinstall packages.

Installing Python packages may require Firebird to have access to its configured
Python package source.

## Run after installation

Double-click:

`launch_gui.command`

The equivalent Terminal command is:

```bash
./launch_gui.command
```

The GUI uses SSH and explicitly invokes the Firebird Python shown in the
connection form. Its default is
`~/miniconda3/envs/idtracker_reprocess_v1/bin/python`. Tkinter is required only
on the Mac.

The interface is divided into three tabs:

- **Setup & Run** contains the SSH connection, scientific parameters, process
  button, and result downloads.
- **Sessions** contains the full approved-session table, filters, start-time
  tools, and trajectory report.
- **Logs & Diagnostics** contains live SSH progress and diagnostic tools.

Workflow:

1. Enter the Firebird pipeline project root. The default is
   `/data/labs/vformic1-swat-lab/idtracker_pipeline_runs`.
2. Scan. This is read-only. Approval comes only from
   `QC/run_status.csv`, where `qc_decision` is `APPROVED` or legacy `DONE`.
3. Repeated approved records are grouped by `(video, cell, analysis)`. Only the
   greatest `date_run` is retained; `run_index` and metadata path break ties.
4. Review the detected interval for every selected session.
5. Correct missing, ambiguous, or zero starts with **Edit selected start frame**.
   Alternatively, use **Export sessions needing start times**, fill only
   `enter_start_global_frame`, and use **Import completed start-time CSV**.
6. Double-click **Process?** to check only a few example sessions.
7. Confirm the inclusive 7200-frame timespan (`end - start`), 30-pixel
   displacement threshold, both ROI-buffer widths, and the fight social
   distance threshold (default 60 pixels).
8. Process, then download the combined CSV and PDF plot folder.

A successful or collected run is never treated as scientifically approved
unless the authoritative QC table marks it approved. Folder names and TOML
locations are not approval evidence.

For the current prototype phase, each selected session atomically replaces its
canonical `processed_result_latest.csv`. A completed batch
atomically replaces `combined_results_latest.csv`, containing all
individual rows plus QC
record, video, cell, analysis type, camera, recording date, recording time,
ACT, processing batch/time, and source-result provenance. Use
**Download combined CSV** to save that batch file on the Mac. The original
complete file remains intact if a replacement calculation fails; partial files
are cleaned up and never become the canonical result. The full calculation specification is in
`METHODS.html`. Proposed Kiran-analysis variables and remaining definition
questions are tracked in `ANALYSIS_REQUIREMENTS_REVIEW.md`.

After a complete processing batch is promoted, the GUI automatically saves a
timestamped copy on the Mac under:

`~/Downloads/IDtracker_postprocessing_results`

The two matching items are
`combined_results_YYYYMMDD_HHMMSS_microseconds.csv` and
`combined_results_YYYYMMDD_HHMMSS_microseconds_pdfs/`. They are staged as
hidden partial items and promoted only after both downloads finish. The manual
download buttons remain available.

In the combined CSV, `cell_label`, `video`, and `analysis_type` (fight or BA)
are deliberately the first three columns. `video_year` is fourth and is parsed
from the recording date for recognized 2025 and 2026 video names.

The editable missing-start report is keyed by authoritative `qc_record_id`.
Import validation is all-or-nothing: duplicate IDs, unknown IDs, non-integers,
zero, and negative starts reject the entire import before any session changes.

The scanner prefers IDtracker gap-filled trajectories in this order:
`validated.npy`, `without_gaps.npy`, `trajectories_wo_gaps.npy`, then
`trajectories_without_gaps.npy`. When none exists, it continues with the best
available raw source in this order: `trajectories.npy`, `trajectories.h5`, then
`trajectories.csv`. The exact choice is visible in the GUI and written as
`trajectory_source_kind`. Only a session with no recognized trajectory of any
supported type is skipped as `NO_USABLE_TRAJECTORY`.

The prototype does not add its own interpolation. Any coordinates that remain
missing in the selected file are reported in the CSV and warning. Raw fallback
rows additionally contain a `RAW_IDTRACKER_INPUT` warning.
`total_distance_px_in_analysis_window` is the sum of valid adjacent-frame
Euclidean steps from the inclusive start through the inclusive end. Missing
segments are excluded without additional interpolation or gap bridging.

Wall-buffer outputs use primary `roi_list[0]` and a GUI-configurable inward
buffer (default 30 pixels). Frame classifications use centroids; distance
classifications use segment midpoints. `spatial_partition_status` checks that
wall plus interior equals each corresponding total and fails explicitly when
valid data lie outside the primary ROI.

Each CSV row explicitly identifies the zero-based IDtracker animal. For
two-animal fights, LEFT/RIGHT is determined only from the x coordinates at the
exact approved analysis-start frame; missing values, ties, and unexpected
animal counts are left explicitly unassigned.

Fight records use `roi_list[1]` as fungus. Frames and midpoint-defined distance
on fungus are partitioned into a configurable inward edge buffer (default
30 pixels) and fungus interior, with explicit additivity checks.

For two-animal fights, one editable social-distance threshold defaults to 60
pixels. The CSV reports the number of frames with both centroids within that
distance and, for each animal, its movement distance across adjacent valid
steps whose two endpoint frames are both within range. A one-animal-missing run
is counted as social disappearance only when it begins immediately after a
within-range frame and the same animal reappears before the inclusive window
ends. Missing coordinates remain missing for latency, distance, wall, and
fungus calculations when the optional substitution switch is off.

`social_return_interaction_events` counts a stricter visible sequence:
together within 60 pixels, then at least one frame with both animals visible
and farther than 60 pixels, then together within 60 pixels again. A
missing-only gap is not treated as proof of separation.

The GUI checkbox **Use social disappearance in distance/location
calculations** defaults to off. When enabled, each qualifying missing animal
receives the visible partner's centroid for those disappearance frames only.
The substituted coordinates are used for total distance and primary-wall and
fungus frame/distance calculations, including movement steps entering and
leaving the substituted run. Latency, social-distance summaries, and original
valid/missing counts remain based on unmodified IDtracker data. Separate CSV
columns record the switch state, animal-specific imputed-frame count, and
effective coordinate frames used in distance/location calculations. The direct
remaining count is also written as
`remaining_missing_coordinate_frames_after_social_substitution`.

Both BA and fight rows include a provisional tight-loop turtling candidate
screen. The default 120-frame sliding window requires at least 120 px of path,
a 90th-percentile radius no larger than 35 px, at least three complete
rotations of cumulative absolute turning, net displacement/path no larger than
0.25, and no valid adjacent step over 20 px. At least 95% of coordinates in a
window must be valid; sub-pixel steps are excluded as jitter. These six editable
thresholds are shown in the GUI. Candidate frames and contiguous events are
reported per animal.

This detector is not a posture classifier: centroid geometry cannot prove that
a beetle is upside down. It was provisionally checked against three boxed
positive PDFs and two unboxed comparison PDFs supplied on 2026-07-24. More
positive and negative examples are required before biological inference.
Potential turtling paths appear as thin semi-transparent dark-red dashed
overlays so the original track remains visible.

Processing creates one multipage PDF per session under the remote
`combined_results_latest_pdfs` folder. Every page includes the full video
filename, cell, accepted trajectory-source category, and QC record provenance.
The GUI's **Download PDFs from this run** button copies
those PDFs to a folder selected on the Mac. The combined CSV and PDF folder are
staged as a complete batch; incomplete processing cannot replace the previously
complete latest batch. Fight PDFs add a distinct social-distance/disappearance
page. The penultimate page is a translucent wall/fungus buffer audit map, and
the metadata page is deliberately last for rapid review.
