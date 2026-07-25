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

The interface is divided into four tabs:

- **Setup & Run** contains the SSH connection, scientific parameters, process
  settings, and result downloads.
- **Sessions** contains the full approved-session table, filters, start-time
  tools, process button, and trajectory report.
- **Jump Audit** contains video-level BA and fight disturbance results and the
  explicit approval button for suggested replacement starts.
- **Logs & Diagnostics** contains live SSH progress and diagnostic tools.

Workflow:

1. Optionally click **Load previous settings or results**. The loader accepts a
   reusable JSON settings bundle, a prior combined-results CSV, or a Jump Audit
   video-summary CSV. Loading before a scan queues saved start decisions for
   exact matching after the approved-session scan.
2. Enter the Firebird pipeline project root. The default is
   `/data/labs/vformic1-swat-lab/idtracker_pipeline_runs`.
3. Scan. This is read-only. Approval comes only from
   `QC/run_status.csv`, where `qc_decision` is `APPROVED` or legacy `DONE`.
4. Repeated approved records are grouped by `(video, cell, analysis)`. Only the
   greatest `date_run` is retained; `run_index` and metadata path break ties.
5. Review the detected interval for every selected session.
6. Correct missing, ambiguous, or zero starts with **Edit selected start frame**.
   Alternatively, use **Export sessions needing start times**, fill only
   `enter_start_global_frame`, and use **Import completed start-time CSV**.
7. Click **Audit jumps in all approved BA + fights**. Review any video-wide
   disturbance recommendation in the Jump Audit tab. No start changes until
   you select a video and click **Approve selected start recommendation**.
8. Click **Save current settings and decisions** after start and Jump Audit
   review. The JSON preserves GUI parameters, positive start decisions with
   provenance, and the current Jump Audit video/track tables.
9. For examples, double-click individual **Process?** cells. For a large
   reviewed batch, filter to **Ready to process** and click
   **Check all filtered ready sessions**.
10. Confirm the inclusive 7200-frame timespan (`end - start`), 30-pixel
   displacement threshold, both ROI-buffer widths, and the fight social
   distance threshold (default 60 pixels).
11. Process, then download the combined CSV and PDF plot folder.

Reusable JSON files default to
`~/Downloads/IDtracker_postprocessing_results/saved_settings/`. They store the
SSH key path but never the private-key contents. A prior combined-results CSV
restores its analysis parameters and deduplicated session starts. A Jump Audit
video CSV also loads its sibling track CSV when available; only rows explicitly
marked `APPROVED` restore video-wide starts. Pending recommendations are shown
but never applied. A separately loaded Jump Audit supplements previously queued
combined-CSV decisions rather than discarding them. Matching first uses the
exact QC record ID and then the exact
`(video, cell, analysis)` key when an approved run has been replaced. Unmatched
or ambiguous records are logged and are never guessed. Every restored start
appends the settings filename and restoration timestamp to its provenance.

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

After a complete processing batch is promoted, the GUI automatically creates
one timestamped completed-run folder under:

`~/Downloads/IDtracker_postprocessing_results/completed_run_YYYYMMDD_HHMMSS_microseconds/`

That folder contains
`combined_results_YYYYMMDD_HHMMSS_microseconds.csv` and `pdfs/`. The timestamp
in the CSV filename is the same processing-batch timestamp used by its enclosing
completed-run folder. The entire folder is first staged under a
hidden `.partial` name and becomes visible only after both the CSV and all PDFs
finish downloading. The manual download buttons remain available.

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
segments are excluded without additional interpolation or gap bridging. The
editable, provisional jump threshold defaults to the researcher-selected value
of 200 pixels. When an adjacent finite step is strictly greater, that movement
step is excluded from latency chains and every distance total. Neither endpoint
coordinate is deleted: both remain eligible for frame-based wall and fungus
counts. Later valid movement steps resume as a new path segment, and no missing
gap or rejected jump is bridged. Raw coordinates are preserved and never
interpolated. The CSV reports `one_frame_jump_threshold_px`,
`one_frame_jumps_excluded`, and `jump_qc_status` for every animal.
`jump_threshold_px` remains as a compatibility alias. The deprecated
`jump_artifact_coordinate_frames_excluded` is zero because this version does
not delete coordinate frames.

The Jump Audit evaluates all approved BA and fight sessions with usable
positive start evidence in one
read-only Firebird pass. A video-wide disturbance requires synchronized jump
evidence from at least three distinct approved sessions and at least half of
the available approved sessions for that video. The proposed start is the next
50-frame boundary after the final synchronized event, and it is offered only
when a complete analysis span fits. Cell- or animal-specific jumps do not
produce a video-level start recommendation.

For a video deliberately marked for manual start review, the read-only audit
may use one positive, unambiguous detected interval to locate disturbances.
This provisional audit start is labeled in the audit CSV and never authorizes
processing. Zero, missing, and conflicting detected intervals remain excluded.
Only clicking the Jump Audit approval button makes the recommended start final.

The main statistical columns use intuitive final-decision names:
`analysis_start_frame` and `analysis_end_frame_inclusive`. The original start
and timestamped approval explanation are archived near the end as
`archived_original_start_frame`, `start_frame_decision_source`, and
`start_frame_decision_provenance`. Detailed video and track evidence is saved
separately under
`~/Downloads/IDtracker_postprocessing_results/jump_audits`.

Latency remains displacement from the exact analysis-entry coordinate, but a
crossing is accepted only while it is connected to that entry coordinate by a
continuous chain of valid adjacent steps at or below the anti-jump threshold.
This prevents a large IDtracker relocation from becoming a false wake event.
PDF track lines break across original missing coordinates and excluded
jump steps; subtle gray x marks show the destination endpoint after each
rejected step, but that coordinate itself is retained.

Post-wake outputs begin at `threshold_crossing_global_frame` and continue
through the inclusive analysis end. The wake frame is included in frame counts;
movement opportunities begin with the step from the wake frame to the next
frame. The primary adjusted movement measure is
`post_wake_total_distance_px / post_wake_valid_movement_steps`. A valid
movement step has finite effective coordinates at both adjacent frames and is
not greater than the 200-pixel jump threshold. Missing gaps and rejected jumps
are never bridged. Wall, fungus, and joint open-and-off-fungus distance
summaries use the same accepted steps and the same segment-midpoint geometry as
the full-window metrics. BA fungus and joint fields are blank with an explicit
`NOT_APPLICABLE_NOT_FIGHT` status. If wake is not reached or the exact baseline
is invalid, post-wake numeric fields are blank rather than zero.

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
calculations** defaults to on. The user can turn it off before processing.
When enabled, each qualifying missing animal
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

For fights, any otherwise qualifying turtling-candidate frame whose original
centroid is on or inside `roi_list[1]` (the fungus ROI) is removed before
candidate frames, proportions, events, and PDF overlays are produced. The
proportion is candidate frames after this fungus exclusion divided by the
animal's original valid detected-coordinate frames in the inclusive analysis
window. BA analyses have no fungus exclusion.

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

Every CSV row and final PDF metadata page records the standalone script
version. After a complete batch is successfully promoted, the Mac GUI plays a
chime and opens an **Everything is done** popup. The popup is not emitted for a
failed or incomplete batch.

## SLURM execution for large batches

The GUI defaults to **SLURM job array**. Each checked, approved, processable
session becomes one array task. The default maximum concurrency is 20 tasks;
this is a scheduler throttle, not a request for 20 CPUs in one task. Each task
requests one CPU, 4 GB of memory, and two hours. The default account is `swat`;
the partition is left blank so Firebird applies the cluster default. All of
these values except the one-CPU design are visible before confirmation.

The GUI uploads an immutable copy of the processor, worker, finalizer,
combiner, and JSON manifest to:

`~/idtracker_reprocessing_v1/slurm_batches/<timestamp>/`

SLURM stdout/stderr logs and one atomic status JSON per session remain in that
batch folder. A dependent `afterany` finalizer runs after the full array,
refuses to proceed unless every manifest task succeeded and produced both its
CSV and PDF, then combines the CSVs, verifies the PDF count, and only then
promotes the complete CSV and PDF directory. A failed,
cancelled, timed-out, or incomplete array cannot replace the previous complete
results. The GUI log reports the array and finalizer job IDs and polls progress
while it remains open.

**Direct SSH (small test only)** remains available for a few examples. The
combined CSV records `processing_execution_mode` as `SLURM_ARRAY` or
`DIRECT_SSH`.
