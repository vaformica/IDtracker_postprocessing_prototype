# Kiran analysis requirements — definitions requiring review

This file separates calculations that are mathematically specified from those
that remain ambiguous. Items in the second section are **not implemented**.

## Current implemented first stage

- Approved global analysis start `S`, never silently zero.
- Requested inclusive timespan `W`, default 7200 frame intervals.
- Inclusive end frame `E = S + W`.
- Included global frames `S ... E`.
- First frame at which Euclidean displacement from the coordinate at `S` is at
  least the threshold `T`, default 30 pixels.
- Latency in frames: `crossing_global_frame - S`.
- Missing-coordinate counts and explicit non-result statuses.
- Original missing frames, social-disappearance substitutions, and remaining
  unusable coordinate frames are reported separately.
- Adjacent movement steps strictly greater than the GUI jump threshold
  (researcher-selected default 200 pixels) are rejected from latency chains,
  distance totals, ROI movement distances, social movement distance, and PDF
  path connections. Endpoint coordinates remain available for frame-based
  location counts. Raw IDtracker files remain untouched.
- Post-wake calculations use the provisional first valid 30-pixel crossing
  through the inclusive end. Their movement-opportunity denominator is the
  number of valid adjacent steps, never elapsed frames. Missing gaps and
  rejected jump steps are not bridged.
- Post-wake wall, fungus, and direct open-and-off-fungus summaries include both
  opportunity-adjusted distance and conditional speed fields with explicit
  partition statuses. BA fungus/joint fields are explicitly not applicable.
- A parsed `video_year` column is populated only for recognized 2025 and 2026
  recording dates.
- Fight-only social-distance summaries use one GUI threshold, default 60
  pixels. Outputs are frames within range, animal-specific distance moved while
  within range, animal-specific social-disappearance frames, and visible
  together-separate-together return events.
- Both BA and fight rows include provisional tight-loop turtling candidate
  frames and contiguous events from the documented sliding-window geometry.

This first-stage threshold is not yet the requested **sustained** displacement
threshold. A sustained rule needs an approved run-length definition.

The turtling measure is also explicitly provisional. It detects centroid paths
consistent with sustained tight looping; it cannot establish upside-down body
posture without video review. Defaults were checked against three boxed
examples and two unboxed comparisons supplied on 2026-07-24, which is not yet
a general validation sample.

## Important corrections and unresolved choices

### 1. Valid timespan: difference versus count

If both endpoints are valid:

- elapsed frame difference = `last_valid_frame - first_valid_frame`;
- number of included frame observations =
  `last_valid_frame - first_valid_frame + 1`.

The project convention is now
`analysis_end_frame_inclusive - analysis_start_frame = 7200`. This represents
7200 adjacent-frame intervals and includes 7201 coordinate observations. For
later denominators, the scientific quantity can still be:

1. frame observations (`+1`), or
2. consecutive-frame movement opportunities (the difference, no `+1`).

For distance per available movement frame, option 2 is dimensionally aligned
with step distances, because a distance step exists between two frames.

### 2. Sustained wake-up definition

Please specify:

- required consecutive frames at or beyond 30 pixels (the old script used 30,
  but this has not been approved here);
- whether one missing coordinate breaks the run (recommended: yes);
- whether the crossing frame is the first frame of the qualifying run or the
  frame at which the required run becomes confirmed.

No sustained wake-up result should be produced until these are fixed.

### 3. Distance after waking — implemented provisional definition

The implemented auditable definition is:

`sum Euclidean distance between adjacent valid coordinates from wake frame
through the inclusive analysis end`.

A missing coordinate breaks the adjacent steps touching it, and a step strictly
greater than 200 pixels is rejected. The script does not bridge either case and
reports missing-frame and rejected-step counts separately. The adjusted value
is pixels per valid adjacent-frame movement opportunity after waking—not pixels
per elapsed frame.

This still uses the first crossing rather than a sustained crossing because the
sustained run-length rule remains unresolved.

### 4. Open-area summaries — implemented definitions

The earlier subtraction
`frames_not_in_roi_border_buffer - total_time_available_to_move` is not used.
The implemented post-wake summaries are:

- open-area proportion = open centroid frames / valid coordinate frames;
- open distance per available step = open midpoint-classified distance / all
  valid post-wake movement steps;
- conditional open speed = open midpoint-classified distance / open-classified
  post-wake steps.

Fight rows use analogous off-fungus summaries and a direct intersection of the
open and off-fungus masks. These are screening summaries pending biological
review, but their numerators and denominators are now mathematically fixed.

### 5. Implemented wall and fungus geometry

The prototype uses `session.json` `roi_list[0]` as the primary arena and, for
fights only, `roi_list[1]` as fungus. Polygon boundary points count as inside.
Both buffers are measured inward using shortest Euclidean distance to the
corresponding polygon edge. Adjacent-frame distance is assigned using the
segment midpoint. Output includes explicit frame and distance additivity checks.

“Patrolling score” remains disabled because it still needs a formula and
biological interpretation.

### 6. Raw-trajectory fallback policy

Firebird inspection on 2026-07-24 confirmed that
`session_Camera_1_40169154_20260630_1633_FIGHT_ACT2_PAPER_DATA_WRONG_6`
contains `trajectories.npy` and `trajectories.h5`, but no `validated.npy` or
recognized without-gaps NPY. The raw NPY has shape `(8335, 2, 2)` and 2,121
frames with at least one missing animal coordinate across the full file.

Under the user-approved fallback policy, this session now uses
`trajectories.npy` when reprocessed. Its source is explicitly
`IDTRACKER_RAW_NPY`; missing coordinates are preserved and reported,
and invalid adjacent-frame distance steps are excluded without bridging.

A read-only inventory of all 439 newest approved video/cell/analysis records on
2026-07-24 found zero recognized `validated.npy` or without-gaps NPY files.
The earlier gap-filled-only restriction is superseded. These sessions may now
continue from raw IDtracker sources. The combined CSV preserves the exact source
category per animal row so raw and gap-filled results cannot be confused.

### 7. Social-distance and disappearance interpretation

The social values are screening summaries, not proof of fighting. One 60-pixel
threshold defines both within-range frames and the entry condition for a
social-disappearance run. The missing animal's coordinates remain missing. The
visible animal's position is copied only when the optional GUI calculation
switch is enabled.

A return interaction event is counted only when both animals are first within
range, are then both visibly farther apart than the threshold for at least one
frame, and later return within range. A missing-only gap cannot establish
separation and does not count as a return event.

The optional switch is on by default. When enabled, the copied partner
centroid is used for total distance and wall/fungus frame and distance
calculations, including entry and exit steps. Latency, original missing counts,
and return-event detection remain based on the original coordinates. Every row
records the switch state and animal-specific number of substituted frames.

## Videos forced to manual start review

The GUI recognizes these names (with or without `.mp4`) and leaves the approved
start blank even if it detects an interval:

- Camera_1_40169154_20260630_1342_FIGHT_ACT1
- Camera_1_40169154_20260629_1319_ACT1.mp4
- Camera_1_40169154_20260627_1614_ACT2.mp4
- Camera_1_40169154_20260627_1316_ACT1.mp4
- Camera_3_40629046_20260627_1635_ACT2.mp4
- Camera_2_40359705_20260627_1619_ACT2.mp4
- Camera_2_40359705_20260628_1604_ACT2.mp4

The scan status reports the total newest-approved sample, how many have a
nonzero detected start, how many need manual entry, and how many match this
collaborator list.
