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
- Fight-only social-distance summaries use one GUI threshold, default 60
  pixels. Outputs are frames within range, animal-specific distance moved while
  within range, animal-specific social-disappearance frames, and visible
  together-separate-together return events.

This first-stage threshold is not yet the requested **sustained** displacement
threshold. A sustained rule needs an approved run-length definition.

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

### 3. Distance after waking

A proposed auditable definition is:

`sum Euclidean distance between adjacent valid coordinates from wake frame
through the last valid frame`.

A missing coordinate would break that individual step; the script would not
bridge a gap and would report excluded-step counts. The proposed adjusted value
would be pixels per valid adjacent-frame step after waking—not pixels per every
elapsed frame—unless a different missing-data policy is approved.

### 4. “Time in the open” note

`frames_not_in_roi_border_buffer - total_time_available_to_move` is not an
adjustment and will generally be zero or negative. Plausible alternatives are:

- open frames after waking;
- `open frames after waking / valid frames available after waking`;
- moving-open frames after waking;
- `moving-open frames / valid frames available after waking`.

The intended numerator, denominator, and pre-/post-wake restriction must be
selected explicitly.

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

The optional switch is off by default. When enabled, the copied partner
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
