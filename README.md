# Firebird minimal post-processing v1

This is a separate, review-first replacement prototype. It does not import or
call the legacy post-processing scripts.

## Read this first

This program converts approved IDtracker.ai trajectories into a deliberately
auditable table of beetle behavior measurements and a matching PDF for visual
review. It was written for scientific research, where a plausible-looking
number is not sufficient: the program must also preserve where that number
came from, which frames were eligible, which steps were rejected, what geometry
was used, and why a value may be blank.

The two most important companion documents are:

- [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md): the student-facing definition of
  every column in the per-session and combined CSV schemas, including units,
  applicability, missing-value meaning, and examples.
- [`METHODS.html`](METHODS.html): the formal mathematical and geometric
  specification used to audit the implementation.

Additional provenance is recorded in:

- [`CHANGELOG.md`](CHANGELOG.md): version-by-version history;
- [`ANALYSIS_REQUIREMENTS_REVIEW.md`](ANALYSIS_REQUIREMENTS_REVIEW.md):
  implemented scientific definitions and unresolved biological choices;
- [`REPOSITORY_STATUS.md`](REPOSITORY_STATUS.md): boundaries between this
  prototype and the production pipeline.

Students should read this README before running the GUI and keep the data
dictionary open when working with the CSV. Column names such as
`post_wake_open_distance_px_per_available_step` are intentionally explicit,
but they encode different numerators and denominators and should not be
shortened casually in analysis code.

## What one output row represents

The combined CSV is in **long format**:

> One row represents one zero-based IDtracker animal in one selected
> video/cell/analysis session.

The ordinary completed-run CSV contains the sessions processed in that batch,
which may still be awaiting post-processing QC. The separate
`approved_results_latest.csv` contains only current newest sessions whose
latest decision in this GUI is `APPROVED`.

A BA session will normally have one animal row. A Fight session is expected to
have two rows, one for IDtracker animal 0 and one for IDtracker animal 1. The
program does not average those fight rows. Biological identity is not inferred
from the numeric IDtracker animal index. For two-animal fights, `starting_side`
records which trajectory began on the LEFT or RIGHT at the exact approved
analysis-start frame so that a later, separately audited metadata workflow can
connect trajectory identity to a beetle library ID.

The same source video can contribute multiple cell sessions. The same
video/cell/analysis can also have repeated IDtracker runs. Version 0.8.0 scans
all IDtracker sessions under the researcher-entered Firebird roots and does
not consult the old pipeline approval CSV. Every repeat remains visible, but
only the deterministic newest run for each `(video, cell, analysis)` key is
eligible for processing and approval in this program.

## What the program does

For every selected newest eligible session, the processor:

1. recursively discovers all IDtracker sessions under the entered roots,
   preserves every repeat, and marks the newest run for each exact
   video/cell/analysis key;
2. resolves the best available IDtracker trajectory file;
3. requires a positive researcher-reviewed global analysis start;
4. extracts one inclusive global-frame analysis window;
5. identifies the first provisional displacement-threshold crossing;
6. calculates accepted adjacent-frame movement distance without bridging
   missing coordinates or rejected jumps;
7. classifies centroid frames and movement-segment midpoints relative to the
   primary wall buffer;
8. for fights, classifies the secondary fungus ROI and its inward buffer;
9. for two-animal fights, screens social proximity, disappearance, and visible
   return interactions;
10. screens provisional tight-loop trajectory patterns that may warrant video
   review for turtling;
11. repeats the post-wake movement/location summaries for both the remaining
    wake-through-end interval and a fixed 3600-frame-interval comparison;
12. writes one CSV row per tracked animal and one multipage audit PDF per
    session;
13. combines only complete session outputs and atomically downloads the CSV and
    verified PDF collection to the Mac; and
14. records independent `UNREVIEWED`, `APPROVED`, or `RERUN` decisions,
    rebuilding the approved-data and rerun-report CSVs without modifying
    IDtracker.

## What the program deliberately does not do

The processor does not:

- modify IDtracker trajectory files;
- add its own interpolation;
- bridge across missing-coordinate gaps;
- treat a large rejected jump as real movement;
- silently replace a missing analysis-start coordinate with a later frame;
- accept an analysis start of zero;
- infer a beetle's biological library ID;
- interpret social proximity as proof of fighting;
- interpret a tight looping centroid path as proof that a beetle is upside
  down;
- invent a sustained wake definition that has not been approved;
- use seconds in the scientific output;
- treat blank numeric values as zero;
- process every run merely because it exists.

## Why this separate prototype exists

An earlier post-processing workflow had accumulated too many columns and some
calculations whose frame windows, denominators, or geometry were not
sufficiently explicit. During review with a student collaborator, several
risks became clear:

- some sessions had an analysis interval beginning at global frame 0, which was
  a data-entry error rather than a biological start;
- aggregate distance and latency values could be calculated over mismatched
  time windows;
- elapsed frames, valid coordinate observations, and valid adjacent movement
  opportunities were being treated too casually as if they were the same
  quantity;
- wall and fungus allocations needed explicit centroid-versus-midpoint
  geometry and additivity checks;
- missing trajectories and apparent jumps caused by tracking disturbances
  could create visually convincing but biologically impossible straight
  segments;
- social disappearance required clear provenance because copying a visible
  partner's centroid is an explicit biological inference, not a raw
  observation;
- provisional turtling detection needed to be conservative and labeled as a
  candidate screen rather than a posture measurement.

This repository therefore started from a smaller set of definitions, retained
useful code only where its behavior could be re-audited, and added tests and
documentation alongside each scientific calculation. It remains separate from
`One_script_to_rule_them_all` so it can be reviewed and revised without
silently changing the larger production QC pipeline.

## Short version history and scientific provenance

- **v0.1.x:** established the independent repository, global-frame analysis
  window, minimal displacement latency, atomic CSV writing, and mathematical
  methods page.
- **v0.2.x:** added missing-coordinate provenance, year parsing, and a
  provisional turtling candidate screen.
- **v0.3.x:** added script-version provenance, fungus exclusion for fight
  turtling, completion alerts, and moved processing controls to the Sessions
  workflow.
- **v0.4.x:** added SLURM arrays, dependent finalization, combined-batch
  completeness checks, and automatic timestamped downloads.
- **v0.5.x:** added explicit trajectory-source priority and raw fallback,
  social disappearance/optional partner-centroid substitution, a single
  60-pixel social threshold, jump auditing with researcher-approved start
  changes, and reusable settings/provenance.
- **v0.6.0:** corrected jump handling to reject adjacent movement **steps**
  strictly greater than the researcher-selected 200-pixel threshold while
  retaining their endpoint coordinates for frame-location summaries. It also
  added wake-through-end opportunity-adjusted movement measures.
- **v0.7.0:** added the separate fixed 3600-frame-interval post-wake block. BA
  rows use the individual animal's wake; both rows of a fight use the later of
  the two wakes.
- **v0.7.1:** changed PDF transfer to one verified archive, moved the final
  chime to actual Mac-download completion, and reorganized the GUI for laptop
  screens.
- **v0.7.2:** added this expanded student guide and a field-by-field data
  dictionary covering all 165 columns in the combined results. Scientific
  calculations, the output schema, and PDF content did not change.
- **v0.8.0:** separated IDtracker execution QC from post-processing QC,
  replaced old-approval scanning with recursive all-session discovery, retained
  and ranked duplicates, added append-only approve/rerun decisions and an
  authoritative approved-results file, and placed missing-coordinate counts
  and percentages prominently on PDF page 1.

The changelog is authoritative for the detailed release record. Older output
files remain scientifically tied to the `script_version` written in each row;
new columns must not be assumed to exist in an old batch.

## Essential vocabulary

### Global frame

The frame number in the original IDtracker trajectory array. The processor does
not reset the approved analysis start to frame 0. For example, if
`analysis_start_frame = 62` and `analysis_timespan_frames = 7200`, then
`analysis_end_frame_inclusive = 7262`.

### Frame interval versus frame observation

An inclusive range from frame 62 through frame 7262 contains:

- 7200 adjacent-frame intervals; and
- 7201 frame observations.

That distinction explains why `analysis_timespan_frames` is 7200 while
`analysis_frame_observations_inclusive` is 7201.

### Coordinate frame

One frame at which the focal animal has a finite x and y centroid. A coordinate
frame supports a location classification such as inside the wall buffer.

### Movement step

The straight-line Euclidean displacement between two adjacent coordinate
frames:

```text
step distance = sqrt((x[f+1] - x[f])^2 + (y[f+1] - y[f])^2)
```

A valid movement step requires finite effective coordinates at both endpoints
and a distance at or below the configured one-frame jump threshold. One missing
coordinate can invalidate the step entering that frame and the step leaving it.
This is why valid coordinate frames and valid movement steps are related but
not interchangeable.

### Frame classification versus distance classification

Wall and fungus **frame counts** classify the centroid at a frame. Wall and
fungus **movement distances** classify the midpoint of the accepted movement
segment. Midpoint assignment prevents one segment from being partly counted in
multiple regions and allows exact distance additivity checks.

### Blank, zero, and status

- `0` means the quantity was applicable and calculated as zero.
- A blank numeric cell means the quantity was not calculated or was not
  applicable; consult the associated status.
- `NOT_APPLICABLE_NOT_FIGHT` means a fight-only fungus or social measure was
  intentionally not defined for a BA.
- A `FAIL_*` status is a QC finding and should not be converted into a usable
  value by analysis code.

## Worked miniature example

Suppose a BA analysis begins at global frame 100, uses a 7200-frame interval,
and crosses the 30-pixel displacement threshold at global frame 400.

```text
analysis_start_frame                 = 100
analysis_end_frame_inclusive         = 7300
analysis_frame_observations_inclusive= 7201
threshold_crossing_global_frame      = 400
latency_to_threshold_frames          = 300
```

The variable wake-through-end block covers frames 400 through 7300. It has
6900 possible adjacent intervals before missing/jump exclusions. The fixed
block covers frames 400 through 4000 and always has 3600 possible adjacent
intervals and 3601 observations when complete.

If the fixed block contains 3580 accepted steps and 17,900 pixels of accepted
distance:

```text
post_wake_3600_distance_px_per_valid_step
    = 17,900 / 3,580
    = 5.0 pixels per valid adjacent movement opportunity
```

This is not “pixels per elapsed second,” and it is not the same as total
distance divided by 3600 when 20 movement opportunities were unavailable.

For a fight in which animal 0 wakes at offset 300 and animal 1 wakes at offset
700, both fight rows use offset 700 as
`post_wake_3600_start_global_frame - analysis_start_frame`. This makes the
fixed fight comparison begin only after both animals have crossed the
provisional wake threshold.

## Student analysis checklist

Before using a combined CSV:

1. Confirm the expected `script_version`.
2. Confirm the row grain and count expected animals per session.
3. Inspect `result_status`, `warning`, and all relevant analysis-status fields.
4. Do not replace blanks with zero.
5. Keep BA and Fight rows separate unless a documented biological join is
   being performed.
6. Verify the intended window: full analysis, wake-through-end, or fixed 3600.
7. Use the matching numerator and denominator; never mix a full-window distance
   with a post-wake denominator.
8. Treat missingness, rejected jumps, raw trajectory fallback, partition
   failures, and turtling as QC/provenance.
9. For fights, verify two rows and review `starting_side` before metadata
   linkage.
10. Preserve `qc_record_id`, batch provenance, source paths, and archived start
    decisions in all derived tables.
11. Report sample sizes before and after every exclusion.
12. Keep the original combined CSV unchanged and write cleaned/analysis-ready
    data to a separate location.

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

The interface is divided into seven tabs:

- **Setup & Run** contains the SSH connection, scientific parameters, process
  settings, and Firebird execution settings.
- **Sessions & Starts** contains every recursively discovered run, filters,
  start-time tools, process button, trajectory status, independent QC status,
  and duplicate status.
- **Post-processing QC** contains the newest eligible run for each
  video/cell/analysis key and the Approve, Rerun, Unreview, PDF-open, and
  report-download controls.
- **Duplicates** preserves every repeated run and explains which run was
  selected as rank 1.
- **Results & Downloads** reports automatic-download progress and contains
  manual CSV/PDF recovery buttons.
- **Jump Audit** contains video-level BA and fight disturbance results and the
  explicit approval button for suggested replacement starts.
- **Logs & Diagnostics** contains live SSH progress and diagnostic tools.

Workflow:

1. Optionally click **Load previous settings or results**. The loader accepts a
   reusable JSON settings bundle, a prior combined-results CSV, or a Jump Audit
   video-summary CSV. Loading before a scan queues saved start decisions for
   exact matching after recursive discovery.
2. Enter one or more Firebird search roots, separated by semicolons. The
   default pipeline-runs root is useful because its run metadata supplies cell
   identity. Add actual 2025/2026 IDtracker session roots when you want bare
   sessions included as well.
3. Click **Recursively find all sessions**. This is read-only. The scanner does
   not read or obey `QC/run_status.csv`: every linked or bare IDtracker session
   found under the entered roots is inventoried.
4. Repeated runs are grouped by `(video, cell, analysis)`. Every run remains in
   the Duplicates tab; only deterministic rank 1 is eligible. A bare
   `session.json` usually lacks the experimental cell, so a session with no
   linked cell metadata is retained as `IDENTITY_INCOMPLETE` and is never
   processed under a guessed identity. A blank run-metadata video may be
   recovered directly from that canonical session's `video_paths[0]`; cell
   labels must still match an uppercase letter followed by digits.
5. Review the detected interval for every selected session.
6. Correct missing, ambiguous, or zero starts with **Edit selected start frame**.
   Alternatively, use **Export sessions needing start times**, fill only
   `enter_start_global_frame`, and use **Import completed start-time CSV**.
7. Click **Audit jumps in all newest BA + fights**. Review any video-wide
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
11. Process. After successful remote completion, leave the GUI open while it
    automatically downloads and verifies the timestamped CSV/PDF folder. The
    final chime and popup identify the completed Mac folder.
12. In **Post-processing QC**, open and review the selected downloaded PDF.
    Page 1 shows the video, cell, and large missing-coordinate count and
    percentage for every IDtracker animal.
13. Click **Approve selected processed session(s)** only when the
    post-processing output is suitable. The animal rows are added to
    Firebird's `postprocessing_qc/approved_results_latest.csv`.
14. If IDtracker should be rerun or its settings changed, click **Mark selected
    for IDtracker rerun** and enter an actionable reason. This updates
    `sessions_marked_rerun_latest.csv`; it does not run or alter IDtracker.

Reusable JSON files default to
`~/Downloads/IDtracker_postprocessing_results/saved_settings/`. They store the
SSH key path but never the private-key contents. A prior combined-results CSV
restores its analysis parameters and deduplicated session starts. A Jump Audit
video CSV also loads its sibling track CSV when available; only rows explicitly
marked `APPROVED` restore video-wide starts. Pending recommendations are shown
but never applied. A separately loaded Jump Audit supplements previously queued
combined-CSV decisions rather than discarding them. Matching first uses the
exact discovered session record ID and then the exact
`(video, cell, analysis)` key when a run has been replaced. Unmatched
or ambiguous records are logged and are never guessed. Every restored start
appends the settings filename and restoration timestamp to its provenance.

An IDtracker session being present, complete, previously approved by the old
pipeline, or newest does not make its post-processing result scientifically
approved. In version 0.8.0, approval comes only from the explicit
**Approve selected processed session(s)** action in this GUI. Newest-run
selection determines which duplicate can be reviewed; it is not itself an
approval.

For the current prototype phase, each selected session writes a uniquely keyed
per-session CSV. A completed batch
atomically replaces `combined_results_latest.csv`, containing all
individual rows plus QC
record, video, cell, analysis type, camera, recording date, recording time,
ACT, processing batch/time, and source-result provenance. Use
**Download combined CSV** to save that not-yet-QC-approved batch file on the
Mac. Download the independent approved data file from the Post-processing QC
tab. The original
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
hidden `.partial` name. Firebird packages all PDFs into one uncompressed ZIP
for transfer, because the already-compressed PDFs are much faster to move as
one file than as hundreds of recursive `scp` members. The Mac accepts only
flat `.pdf` archive members, verifies the expected count, extracts them into
`pdfs/`, removes the temporary ZIP, and makes the completed-run folder visible
only after both the CSV and verified PDFs are present. The manual recovery
download buttons are in the separate **Results & Downloads** tab.

### Independent post-processing QC files

The configured Firebird output root contains a separate
`postprocessing_qc/` folder:

- `postprocessing_qc_decision_history.csv` is append-only. Every approval,
  rerun, and return-to-unreviewed click creates a new timestamped event with
  reviewer, reason, session/trajectory paths, duplicate rank, processing batch,
  and script version.
- `postprocessing_qc_current.csv` contains the latest decision for every
  session record.
- `approved_results_latest.csv` is rebuilt from current rank-1 sessions whose
  latest decision is exactly `APPROVED`. It contains one row per IDtracker
  animal and adds eight `postprocessing_qc_*` provenance columns.
- `sessions_marked_rerun_latest.csv` contains current rank-1 sessions whose
  latest decision is `RERUN`, including the human-entered reason and paths
  needed to locate the IDtracker run.

The approved file is rebuilt rather than blindly appended. If an approved
session is later marked `RERUN` or `UNREVIEWED`, its animal rows leave the
approved file while the complete history remains. If recursive discovery finds
a newer duplicate, the earlier approval is not transferred to it: the new run
must be processed and reviewed on its own.

In the combined CSV, `cell_label`, `video`, and `analysis_type` (fight or BA)
are deliberately the first three columns. `video_year` is fourth and is parsed
from the recording date for recognized 2025 and 2026 video names.

The editable missing-start report is keyed by the discovered
`session_record_id`, carried in the compatibility-named `qc_record_id` field.
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

The Jump Audit evaluates all newest eligible BA and fight sessions with usable
positive start evidence in one
read-only Firebird pass. A video-wide disturbance requires synchronized jump
evidence from at least three distinct newest sessions and at least half of
the available newest sessions for that video. The proposed start is the next
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

The CSV also contains a separate, fixed-length `post_wake_3600_*` block. It
does not replace the wake-through-end fields above. For a BA animal, the fixed
block begins at that animal's threshold-crossing frame. For a two-animal fight,
both rows begin at the later of the two crossing frames, so the two animals are
compared over the same interval after both have awakened. The inclusive range
contains 3600 adjacent-frame intervals and 3601 coordinate observations. A
complete interval is required; if either fight animal has no wake frame or the
fixed end would exceed the approved analysis end, the fixed-window numeric
fields are blank with an explicit status. The block repeats the total,
wall/open, fight-only fungus, and direct open-and-off-fungus measures and their
valid-step denominators, including the fungus edge-buffer/interior partition.
It also reports fixed-window social contact,
social-disappearance, return-interaction, substitution/missingness, and
provisional turtling summaries. Global thresholds and switch settings remain
single-copy columns elsewhere in the row to avoid redundant provenance
columns. “3600” is calculated strictly as frames, not seconds.

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
filename, cell, accepted trajectory-source category, and discovered session
record provenance. Page 1 also contains a large boxed
**MISSING COORDINATES** banner for every animal:
`missing frames / inclusive frame observations (percentage)`. This is a QC
display only; it does not change or filter coordinates.
The GUI automatically transfers those PDFs in one archive after a successful
run. The **Results & Downloads** tab retains manual CSV and PDF recovery
buttons. The combined CSV and PDF folder are staged as a complete batch;
incomplete processing cannot replace the previously complete latest batch.
Fight PDFs add a distinct social-distance/disappearance page. The penultimate
page is a translucent wall/fungus buffer audit map, and the metadata page is
deliberately last for rapid review.

Every CSV row and final PDF metadata page records the standalone script
version. Remote processing completion begins the automatic download but does
not produce the final alert. Only after the CSV is present, the PDF archive has
been downloaded and verified, and the local completed-run folder has been
promoted does the Mac GUI play a chime and open a **Download complete** popup.
The popup is not emitted for a failed, incomplete, or partial download.

## SLURM execution for large batches

The GUI defaults to **SLURM job array**. Each checked, newest eligible, processable
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
