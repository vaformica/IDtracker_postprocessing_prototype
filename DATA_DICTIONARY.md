# IDtracker post-processing data dictionary

Version documented: **0.7.2**

This document defines every column written by the standalone IDtracker
post-processing prototype. It covers:

- the 151-column per-session processor CSV; and
- the 165-column combined CSV, which adds video, cell, QC, and processing-batch
  metadata.

The combined CSV is the normal input for downstream R analysis.

## Table grain

One combined-output row is:

> one zero-based IDtracker animal in one approved video/cell/analysis session.

A normal BA session generally contributes one row. A normal Fight session
generally contributes two rows. The two fight rows must not be averaged merely
because they share a session. `idtracker_animal_id` is a trajectory-array
index, not a beetle library ID.

## Units and conventions

| Term | Meaning |
|---|---|
| global frame | Index in the original trajectory array. The approved analysis start is not renumbered to zero. |
| frame observation | One centroid observation at one frame. An inclusive 7200-interval range contains 7201 observations. |
| movement step | Euclidean displacement between two adjacent frames. A step requires two endpoints. |
| px | Pixels in the IDtracker coordinate system. No physical-unit calibration is applied. |
| px per valid step | Distance divided by accepted adjacent movement opportunities, not by elapsed seconds. |
| proportion | A unitless value normally from 0 through 1. Multiply by 100 only for display as a percentage. |
| blank numeric cell | Not calculated or not applicable. It is not zero. Read the associated status. |
| zero | Applicable and calculated as zero. |

All scientific time-like outputs are expressed as frames, frame observations,
or adjacent-frame steps. The processor does not convert to seconds.

## Core equations

For adjacent frames `f` and `f + 1`, the step length is:

```text
sqrt((x[f+1] - x[f])^2 + (y[f+1] - y[f])^2)
```

A movement step is accepted only when both effective endpoint coordinates are
finite and its length is at or below `one_frame_jump_threshold_px`. Missing
gaps and rejected jumps are never bridged.

Frame-location values classify the animal's centroid. Movement-location values
classify the midpoint of the accepted segment. This distinction applies to
wall and fungus calculations.

## Reading status fields

Always filter or summarize with the corresponding status. Common patterns are:

- `CALCULATED` or `PASS`: the relevant result was calculated and its internal
  checks passed;
- `NOT_APPLICABLE_NOT_FIGHT`: the variable is intentionally undefined for BA;
- `NOT_CALCULATED_*`: a required wake, ROI, animal count, or valid movement
  opportunity was unavailable;
- `FAIL_*`: a QC or partition check failed and the values require review.

Do not convert blanks associated with these statuses into zero.

## Combined-file identity and batch metadata

These columns are added when complete per-session CSVs are combined.

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `cell_label` | text | combined CSV | Cell or arena label associated with the authoritative approved QC record. It is part of the session identity and should be retained in joins. | `A3` |
| `video` | text | combined CSV | Source video filename recorded by QC. Use the complete value; do not infer identity from a shortened display label. | `Camera_2_40359705_20260701_1336_FIGHT_ACT1.mp4` |
| `analysis_type` | categorical text | combined CSV | Analysis family supplied by the approved record. Expected values are `ba` and `fight`. Unexpected or blank values must be audited rather than guessed from the filename. | `fight` |
| `video_year` | four-digit text | combined CSV | Recording year parsed only when the filename contains a recognized 2025 or 2026 recording date. Blank means parsing did not produce an approved year, not that the year is zero. | `2026` |
| `qc_record_id` | text | combined CSV | Unique identifier of the authoritative approved QC record selected for this session. This is essential provenance for tracing the result back to approval history. | `Camera_2_..._A3_A00001_20260722_073959` |
| `camera` | text/integer-like | combined CSV | Camera number parsed from a `Camera_<number>_<camera_id>_<date>_<time>` filename pattern. Blank means the name did not match the parser. | `2` |
| `camera_id` | text/integer-like | combined CSV | Hardware or project camera identifier parsed immediately after the camera number. Keep it as text to preserve the original identifier. | `40359705` |
| `recording_date` | `YYYYMMDD` text | combined CSV | Eight-digit recording date parsed from the video name. This is the recording date, not the IDtracker processing date. | `20260701` |
| `recording_time` | `HHMM` text | combined CSV | Four-digit recording time parsed from the video name. It has no seconds or timezone information. | `1336` |
| `act` | categorical text | combined CSV | Parsed `ACT` token, normally `ACT1` or `ACT2`. Blank means no recognized ACT token was present. | `ACT1` |
| `processing_batch_id` | timestamp-like text | combined CSV | Unique GUI batch token shared by every row generated in one processing submission. It also appears in the downloaded completed-run folder name. | `20260725_002119_638080` |
| `processing_created_at` | ISO-8601 text | combined CSV | Mac-local date and time when the processing batch was created, including its timezone offset. This is not the recording time. | `2026-07-25T00:21:19-04:00` |
| `processing_execution_mode` | categorical text | combined CSV | Execution route used for the row: normally `SLURM_ARRAY` for large batches or `DIRECT_SSH` for small tests. | `SLURM_ARRAY` |
| `source_result_file` | remote path text | combined CSV | Exact per-session CSV read by the combiner. It permits reconstruction of which complete session result contributed the row. | `/home/.../results/00042.csv` |

## Script, analysis window, identity, latency, and total movement

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `script_version` | semantic-version text | all rows | Exact standalone processor version that generated the row. Results from different versions must not be assumed to share a schema or definition. | `0.7.2` |
| `analysis_start_frame` | integer global frame | all rows | Final positive researcher-reviewed global frame used as the inclusive analysis start. Zero is rejected as a data-entry error. | `760` |
| `analysis_timespan_frames` | integer frame intervals | all rows | Requested difference between inclusive end and start. The default is 7200 intervals, not 7200 observations. | `7200` |
| `analysis_end_frame_inclusive` | integer global frame | all rows | Inclusive end, calculated as `analysis_start_frame + analysis_timespan_frames`. | `7960` |
| `analysis_frame_observations_inclusive` | integer observations | all rows | Number of included frame observations, equal to `analysis_timespan_frames + 1`. | `7201` |
| `movement_threshold_px` | numeric px | all rows | Displacement-from-baseline threshold used for provisional wake detection. The GUI default is 30 px. | `30` |
| `idtracker_animal_id` | zero-based integer | all rows | Animal-axis index in the selected IDtracker trajectory array. It is not a biological identity. | `0` |
| `starting_side` | categorical text | fight; explicit N/A for BA | For exactly two fight animals, `LEFT` is the smaller x coordinate at the exact approved start and `RIGHT` is the larger. Missing/tied/unexpected cases are explicitly unassigned. | `LEFT` |
| `threshold_crossing_global_frame` | integer global frame or blank | all rows | First frame whose distance from the exact start coordinate reaches the movement threshold through a continuous chain of accepted original steps. Blank means no valid crossing. | `1042` |
| `latency_to_threshold_frames` | integer frame intervals or blank | all rows | `threshold_crossing_global_frame - analysis_start_frame`. This is provisional latency to move, not a sustained-wake measure. | `282` |
| `total_distance_px_in_analysis_window` | numeric px or blank | all rows | Sum of accepted effective-coordinate movement steps over the full approved analysis window. If social substitution is enabled, qualifying copied partner coordinates can affect this distance. | `18452.73` |

### Latency example

If the approved start is 760 and the threshold crossing is 1042:

```text
latency_to_threshold_frames = 1042 - 760 = 282 frames
```

The crossing is not accepted if reaching it requires crossing an original
missing-coordinate gap or a step over the jump threshold.

## One-frame jump QC

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `one_frame_jump_threshold_px` | numeric px per adjacent step | all rows | Researcher-selected maximum accepted adjacent movement step. A step exactly equal to the threshold is accepted; only a step strictly greater is rejected. Current default: 200 px. | `200` |
| `one_frame_jumps_excluded` | integer steps | all rows | Number of effective adjacent steps rejected for being strictly greater than the threshold. Endpoints remain available for frame-location counts. | `3` |
| `jump_threshold_px` | numeric px | all rows | Compatibility alias of `one_frame_jump_threshold_px`. New analysis code should prefer the more explicit column. | `200` |
| `jump_artifact_coordinate_frames_excluded` | integer frames | all rows; deprecated | Compatibility field retained from an older design. It is zero because current QC rejects steps rather than deleting endpoint coordinates. | `0` |
| `jump_qc_status` | categorical text | all rows | Summary such as `PASS_NO_JUMPS_OVER_THRESHOLD` or `ONE_FRAME_JUMP_STEPS_EXCLUDED`. Use it as QC, not as a behavioral measurement. | `ONE_FRAME_JUMP_STEPS_EXCLUDED` |

## Variable-length wake-through-end calculations

This block begins at the focal animal's
`threshold_crossing_global_frame` and continues through
`analysis_end_frame_inclusive`. Different animals can therefore have different
available post-wake durations. It is retained alongside, not replaced by, the
fixed 3600-interval block.

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `post_wake_analysis_status` | categorical text | all rows | Whether core wake-through-end calculations were available. Reasons for blanks include invalid baseline, threshold not reached, or no valid movement steps. | `CALCULATED` |
| `post_wake_wall_analysis_status` | categorical text | all rows | Availability/additivity status for post-wake primary-ROI wall/open calculations. | `PASS` |
| `post_wake_fungus_analysis_status` | categorical text | fight; explicit N/A for BA | Availability/additivity status for direct post-wake on/off fungus calculations. | `PASS` |
| `post_wake_open_off_fungus_analysis_status` | categorical text | fight; explicit N/A for BA | Status for the direct intersection of open-area and off-fungus masks. | `PASS` |
| `post_wake_valid_coordinate_frames` | integer frames | calculated rows | Effective finite centroid frames from wake through the inclusive analysis end. This can include qualifying social substitutions when enabled. | `6412` |
| `post_wake_valid_movement_steps` | integer steps | calculated rows | Accepted adjacent effective-coordinate steps whose left endpoint is at or after wake. This is the opportunity denominator for several rates. | `6388` |
| `post_wake_missing_coordinate_frames` | integer frames | calculated rows | Original IDtracker missing frames from wake through end, before any social substitution. | `24` |
| `post_wake_jump_excluded_steps` | integer steps | calculated rows | Effective adjacent steps over the configured jump threshold in the wake-through-end range. | `2` |
| `post_wake_total_distance_px` | numeric px | calculated rows | Sum of accepted effective movement steps from wake through the inclusive end. | `15970.0` |
| `post_wake_distance_px_per_valid_step` | numeric px/valid step | calculated rows | `post_wake_total_distance_px / post_wake_valid_movement_steps`. This adjusts for available movement opportunities, not elapsed seconds. | `2.50` |
| `post_wake_frames_inside_wall_buffer` | integer frames | wall status available | Effective centroid frames inside the primary ROI and no farther than `wall_buffer_px` from its boundary. | `3100` |
| `post_wake_frames_outside_wall_buffer` | integer frames | wall status available | Effective centroid frames inside the primary ROI and farther inward than the wall buffer; this is the defined open area. | `3312` |
| `post_wake_open_area_proportion` | proportion | wall status `PASS` | `post_wake_frames_outside_wall_buffer / post_wake_valid_coordinate_frames`. | `0.5165` |
| `post_wake_distance_px_inside_wall_buffer` | numeric px | wall status available | Accepted post-wake distance whose segment midpoint lies inside the wall buffer. | `6900.0` |
| `post_wake_distance_px_outside_wall_buffer` | numeric px | wall status available | Accepted post-wake distance whose segment midpoint lies in the open area. | `9070.0` |
| `post_wake_steps_inside_wall_buffer` | integer steps | wall status available | Accepted post-wake steps whose midpoint lies inside the wall buffer. | `3000` |
| `post_wake_steps_outside_wall_buffer` | integer steps | wall status available | Accepted post-wake steps whose midpoint lies in the open area. | `3388` |
| `post_wake_open_distance_px_per_available_step` | numeric px/all valid post-wake steps | wall status `PASS` | Open-area distance divided by **all** valid post-wake steps. It measures open-area movement allocated across all available opportunities. | `1.42` |
| `post_wake_speed_px_per_open_step` | numeric px/open-classified step | wall status `PASS` | Open-area distance divided only by steps whose midpoint is open. It is conditional movement speed while in the open. | `2.68` |
| `post_wake_frames_on_fungus` | integer frames | fight | Effective post-wake centroid frames on or inside the secondary fungus ROI. | `900` |
| `post_wake_frames_off_fungus` | integer frames | fight | Effective post-wake centroid frames not on the secondary fungus ROI. Together with on-fungus frames, it partitions valid frames. | `5512` |
| `post_wake_distance_px_on_fungus` | numeric px | fight | Accepted post-wake distance whose segment midpoint is on fungus. | `2200.0` |
| `post_wake_distance_px_off_fungus` | numeric px | fight | Accepted post-wake distance whose segment midpoint is off fungus. | `13770.0` |
| `post_wake_steps_on_fungus` | integer steps | fight | Accepted post-wake steps classified on fungus by midpoint. | `850` |
| `post_wake_steps_off_fungus` | integer steps | fight | Accepted post-wake steps classified off fungus by midpoint. | `5538` |
| `post_wake_off_fungus_proportion` | proportion | fight | `post_wake_frames_off_fungus / post_wake_valid_coordinate_frames`. | `0.8596` |
| `post_wake_off_fungus_distance_px_per_available_step` | numeric px/all valid post-wake steps | fight | Off-fungus distance divided by all valid post-wake steps. | `2.16` |
| `post_wake_speed_px_per_off_fungus_step` | numeric px/off-fungus step | fight | Off-fungus distance divided only by off-fungus steps. | `2.49` |
| `post_wake_frames_open_and_off_fungus` | integer frames | fight with both ROI partitions | Direct count of frames simultaneously in the primary-ROI open area and off fungus. It is not inferred by subtracting marginal totals. | `2900` |
| `post_wake_distance_px_open_and_off_fungus` | numeric px | fight with both ROI partitions | Accepted distance whose midpoint is simultaneously open and off fungus. | `7900.0` |
| `post_wake_steps_open_and_off_fungus` | integer steps | fight with both ROI partitions | Accepted steps whose midpoint is simultaneously open and off fungus. | `3000` |
| `post_wake_open_off_fungus_proportion` | proportion | fight with both ROI partitions | Joint open-and-off-fungus frames divided by valid post-wake coordinate frames. | `0.4523` |
| `post_wake_open_off_fungus_distance_px_per_available_step` | numeric px/all valid post-wake steps | fight | Joint open/off-fungus distance divided by all valid post-wake steps. | `1.24` |
| `post_wake_speed_px_per_open_off_fungus_step` | numeric px/joint-classified step | fight | Joint open/off-fungus distance divided only by joint-classified steps. | `2.63` |

### Two different “open movement” rates

These columns answer different biological questions:

```text
post_wake_open_distance_px_per_available_step
    = open distance / every valid post-wake step

post_wake_speed_px_per_open_step
    = open distance / only open-classified steps
```

The first combines open-area use and movement. The second is conditional speed
after the animal is already in the open. They must not be renamed to the same
generic “open movement” variable.

## Fixed 3600-frame-interval post-wake calculations

When available, this block contains exactly 3600 adjacent-frame intervals and
3601 inclusive coordinate observations.

- BA: the anchor is the focal animal's own wake crossing.
- Fight: both animal rows use the later of the two wake crossings.

If a complete interval does not fit or a required wake is missing, numeric
fields are blank and the status explains why.

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `post_wake_3600_analysis_status` | categorical text | all rows | Availability/core calculation status for the complete fixed block. | `CALCULATED` |
| `post_wake_3600_anchor_rule` | categorical text | all rows | `INDIVIDUAL_WAKE_THRESHOLD_CROSSING` for BA or `BOTH_ANIMALS_WAKE_LATER_CROSSING` for Fight. | `BOTH_ANIMALS_WAKE_LATER_CROSSING` |
| `post_wake_3600_start_global_frame` | integer global frame | available fixed block | Inclusive fixed-window start. Both rows of one normal fight have the same value. | `1460` |
| `post_wake_3600_end_global_frame_inclusive` | integer global frame | available fixed block | `post_wake_3600_start_global_frame + 3600`. | `5060` |
| `post_wake_3600_frame_intervals` | integer intervals | available fixed block | Constant number of adjacent-frame intervals: 3600. | `3600` |
| `post_wake_3600_frame_observations_inclusive` | integer observations | available fixed block | Constant number of inclusive coordinate observations: 3601. | `3601` |
| `post_wake_3600_wall_analysis_status` | categorical text | all rows | Wall/open availability and additivity status inside the fixed block. | `PASS` |
| `post_wake_3600_fungus_analysis_status` | categorical text | fight; explicit N/A for BA | On/off fungus availability/additivity status inside the fixed block. | `PASS` |
| `post_wake_3600_open_off_fungus_analysis_status` | categorical text | fight; explicit N/A for BA | Status for the fixed direct open-and-off-fungus intersection. | `PASS` |
| `post_wake_3600_valid_coordinate_frames` | integer frames | available fixed block | Effective finite centroid frames inside the 3601-observation fixed range. | `3590` |
| `post_wake_3600_valid_movement_steps` | integer steps | available fixed block | Accepted adjacent movement opportunities inside the fixed range. It can be less than 3600. | `3576` |
| `post_wake_3600_missing_coordinate_frames` | integer frames | available fixed block | Original IDtracker missing frames inside the fixed range before substitution. | `11` |
| `post_wake_3600_jump_excluded_steps` | integer steps | available fixed block | Effective fixed-range adjacent steps rejected for exceeding the jump threshold. | `2` |
| `post_wake_3600_total_distance_px` | numeric px | available with valid steps | Sum of accepted effective movement in the fixed range. | `8940.0` |
| `post_wake_3600_distance_px_per_valid_step` | numeric px/valid step | available with valid steps | Fixed total distance divided by fixed valid movement steps. | `2.50` |
| `post_wake_3600_frames_inside_wall_buffer` | integer frames | fixed wall status available | Fixed-range centroid frames inside the primary wall buffer. | `1700` |
| `post_wake_3600_frames_outside_wall_buffer` | integer frames | fixed wall status available | Fixed-range centroid frames in the primary-ROI open area. | `1890` |
| `post_wake_3600_open_area_proportion` | proportion | fixed wall status `PASS` | Fixed open frames divided by fixed valid coordinate frames. | `0.5265` |
| `post_wake_3600_distance_px_inside_wall_buffer` | numeric px | fixed wall status available | Fixed accepted distance assigned to the wall buffer by midpoint. | `3900.0` |
| `post_wake_3600_distance_px_outside_wall_buffer` | numeric px | fixed wall status available | Fixed accepted distance assigned to open area by midpoint. | `5040.0` |
| `post_wake_3600_steps_inside_wall_buffer` | integer steps | fixed wall status available | Fixed accepted steps whose midpoint lies in the wall buffer. | `1660` |
| `post_wake_3600_steps_outside_wall_buffer` | integer steps | fixed wall status available | Fixed accepted steps whose midpoint lies in open area. | `1916` |
| `post_wake_3600_open_distance_px_per_available_step` | numeric px/all fixed valid steps | fixed wall status `PASS` | Fixed open distance divided by all fixed valid movement steps. | `1.41` |
| `post_wake_3600_speed_px_per_open_step` | numeric px/fixed open step | fixed wall status `PASS` | Fixed open distance divided only by fixed open-classified steps. | `2.63` |
| `post_wake_3600_frames_on_fungus` | integer frames | fight | Fixed effective centroid frames on fungus. | `500` |
| `post_wake_3600_frames_off_fungus` | integer frames | fight | Fixed effective centroid frames off fungus. | `3090` |
| `post_wake_3600_frames_in_fungus_edge_buffer` | integer frames | fight | On-fungus fixed frames no farther than `fungus_buffer_px` inward from the fungus boundary. | `320` |
| `post_wake_3600_frames_in_fungus_interior` | integer frames | fight | On-fungus fixed frames farther inward than the fungus edge buffer. Edge plus interior equals on-fungus frames when the partition passes. | `180` |
| `post_wake_3600_distance_px_on_fungus` | numeric px | fight | Fixed accepted distance whose midpoint is on fungus. | `1300.0` |
| `post_wake_3600_distance_px_off_fungus` | numeric px | fight | Fixed accepted distance whose midpoint is off fungus. | `7640.0` |
| `post_wake_3600_distance_px_in_fungus_edge_buffer` | numeric px | fight | Fixed on-fungus accepted distance whose midpoint is within the inward fungus edge buffer. | `850.0` |
| `post_wake_3600_distance_px_in_fungus_interior` | numeric px | fight | Fixed on-fungus accepted distance whose midpoint lies in the fungus interior. Edge plus interior equals on-fungus distance when available. | `450.0` |
| `post_wake_3600_steps_on_fungus` | integer steps | fight | Fixed accepted steps classified on fungus by midpoint. | `480` |
| `post_wake_3600_steps_off_fungus` | integer steps | fight | Fixed accepted steps classified off fungus by midpoint. | `3096` |
| `post_wake_3600_off_fungus_proportion` | proportion | fight | Fixed off-fungus frames divided by fixed valid coordinate frames. | `0.8607` |
| `post_wake_3600_off_fungus_distance_px_per_available_step` | numeric px/all fixed valid steps | fight | Fixed off-fungus distance divided by all fixed valid steps. | `2.14` |
| `post_wake_3600_speed_px_per_off_fungus_step` | numeric px/fixed off-fungus step | fight | Fixed off-fungus distance divided only by fixed off-fungus steps. | `2.47` |
| `post_wake_3600_frames_open_and_off_fungus` | integer frames | fight with both ROI partitions | Direct fixed count simultaneously open and off fungus. | `1650` |
| `post_wake_3600_distance_px_open_and_off_fungus` | numeric px | fight with both ROI partitions | Direct fixed accepted distance simultaneously open and off fungus by midpoint. | `4300.0` |
| `post_wake_3600_steps_open_and_off_fungus` | integer steps | fight with both ROI partitions | Direct fixed accepted steps simultaneously open and off fungus. | `1700` |
| `post_wake_3600_open_off_fungus_proportion` | proportion | fight | Fixed joint frames divided by fixed valid coordinate frames. | `0.4596` |
| `post_wake_3600_open_off_fungus_distance_px_per_available_step` | numeric px/all fixed valid steps | fight | Fixed joint distance divided by all fixed valid steps. | `1.20` |
| `post_wake_3600_speed_px_per_open_off_fungus_step` | numeric px/fixed joint step | fight | Fixed joint distance divided only by fixed joint-classified steps. | `2.53` |
| `post_wake_3600_social_analysis_status` | categorical text | fight; explicit N/A for BA | Availability status for fixed social summaries; exactly two fight animals are required. | `CALCULATED_FIGHT_TWO_ANIMALS` |
| `post_wake_3600_frames_within_social_distance` | integer frames | two-animal fight | Fixed frames with both original centroids visible and separated by no more than `social_distance_threshold_px`. | `240` |
| `post_wake_3600_distance_moved_px_while_within_social_distance` | numeric px | two-animal fight | Focal-animal accepted fixed distance for steps whose two endpoint frames are both within social range. | `610.0` |
| `post_wake_3600_social_disappearance_frames` | integer frames | two-animal fight | Focal-animal qualifying disappearance frames that fall inside the fixed range. Run classification may use entry/reappearance evidence elsewhere in the approved full window. | `8` |
| `post_wake_3600_social_return_interaction_events` | integer events | two-animal fight | Count of visible together → visibly separate → together sequences wholly observable inside the fixed range. | `3` |
| `post_wake_3600_social_disappearance_imputed_frames` | integer frames | two-animal fight | Qualifying fixed disappearance frames for which the partner centroid was actually copied because the switch was enabled. | `8` |
| `post_wake_3600_remaining_missing_coordinate_frames_after_social_substitution` | integer frames | available fixed block | Original fixed missing frames minus actual fixed social substitutions. For BA, this equals original fixed missing frames. | `3` |
| `post_wake_3600_coordinate_frames_used_in_distance_and_location_calculations` | integer frames | available fixed block | Effective finite fixed coordinate frames after any enabled substitution. | `3598` |
| `post_wake_3600_turtling_candidate_frames` | integer frames | available fixed block | Frames in the fixed range marked by the full-window provisional tight-loop detector after fight fungus exclusion. | `120` |
| `post_wake_3600_turtling_candidate_proportion_of_detected_frames` | proportion | available fixed block | Fixed candidate frames divided by original detected coordinate frames in the fixed range. Fight time on fungus remains in the denominator. | `0.0335` |
| `post_wake_3600_turtling_candidate_events` | integer events | available fixed block | Contiguous candidate runs after the full detector mask is restricted to the fixed range. | `1` |
| `post_wake_3600_turtling_detector_status` | categorical text | available fixed block | Provisional detector status associated with the fixed summary. | `CALCULATED_PROVISIONAL_CENTROID_PATH_CANDIDATES` |

## Full-window primary wall-buffer calculations

The primary arena is `roi_list[0]`. A centroid must be inside the primary ROI
before it can be classified as wall-buffer or open. Valid coordinates outside
the primary ROI cause the partition status to fail rather than being silently
assigned.

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `wall_buffer_px` | numeric px | all rows | Inward distance from the primary polygon boundary defining the wall buffer. GUI default: 30 px. | `30` |
| `frames_inside_wall_buffer` | integer frames | primary ROI available | Effective valid centroid frames inside the primary ROI and within the wall-buffer distance. | `3550` |
| `frames_outside_wall_buffer` | integer frames | primary ROI available | Effective valid centroid frames inside the primary ROI and farther inward than the wall buffer. | `2796` |
| `distance_px_inside_wall_buffer` | numeric px | primary ROI available | Full-window accepted distance whose midpoint lies in the wall buffer. | `784.74` |
| `distance_px_outside_wall_buffer` | numeric px | primary ROI available | Full-window accepted distance whose midpoint lies in the open area. | `814.67` |
| `spatial_partition_status` | categorical text | all rows | `PASS` when wall/open frames and distances account for all effective valid data inside the primary ROI; otherwise an explicit failure or unavailable status. | `PASS` |

When `spatial_partition_status = PASS`:

```text
frames_inside_wall_buffer + frames_outside_wall_buffer
    = coordinate_frames_used_in_distance_and_location_calculations

distance_px_inside_wall_buffer + distance_px_outside_wall_buffer
    = total_distance_px_in_analysis_window
```

## Full-window fight fungus calculations

The fungus is `roi_list[1]` and is defined only for Fight sessions.

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `fungus_buffer_px` | numeric px or blank | fight | Inward edge-buffer width applied to the secondary fungus polygon. Blank for BA. | `30` |
| `frames_on_fungus` | integer frames | fight | Effective centroid frames on the boundary or inside the fungus ROI. | `855` |
| `frames_in_fungus_edge_buffer` | integer frames | fight | On-fungus frames within the configured inward distance from the fungus boundary. | `520` |
| `frames_in_fungus_interior` | integer frames | fight | On-fungus frames farther inward than the fungus edge buffer. | `335` |
| `distance_px_on_fungus` | numeric px | fight | Accepted full-window distance whose segment midpoint lies on fungus. | `498.02` |
| `distance_px_in_fungus_edge_buffer` | numeric px | fight | On-fungus distance whose midpoint lies in the inward fungus edge buffer. | `310.20` |
| `distance_px_in_fungus_interior` | numeric px | fight | On-fungus distance whose midpoint lies in the fungus interior. | `187.82` |
| `fungus_partition_status` | categorical text | fight; explicit N/A for BA | Checks that fungus edge-buffer plus interior frames/distances equal the corresponding on-fungus totals. | `PASS` |

## Full-window fight social calculations and optional substitution

These are screening summaries. They do not prove aggression or physical
contact.

A qualifying social disappearance run requires:

1. exactly one animal becomes missing while the partner remains visible;
2. the immediately preceding frame had both animals within the social
   threshold; and
3. the missing animal reappears before the inclusive analysis end.

If substitution is enabled, the visible partner's centroid is copied only into
those qualifying missing frames for distance and location calculations. The raw
trajectory and original missing counts are unchanged.

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `social_distance_threshold_px` | numeric px or blank | fight | Single centroid-separation threshold used for within-range frames and disappearance entry. GUI default: 60 px. | `60` |
| `frames_within_social_distance` | integer frames | two-animal fight | Full-window frames with both original centroids visible and separated by no more than the social threshold. | `430` |
| `distance_moved_px_while_within_social_distance` | numeric px | two-animal fight | Focal-animal accepted distance for steps whose two endpoint frames are both within social range. | `1289.09` |
| `social_disappearance_frames` | integer frames | two-animal fight | Focal-animal missing frames in qualifying social-disappearance runs. | `8` |
| `social_return_interaction_events` | integer events | two-animal fight | Count of visible together → at least one visibly separate frame → together sequences. A missing-only gap does not prove separation. | `4` |
| `social_analysis_status` | categorical text | all rows | Fight social-calculation status or `NOT_APPLICABLE_NOT_FIGHT` for BA. | `CALCULATED_FIGHT_TWO_ANIMALS` |
| `use_social_disappearance_in_calculations` | categorical YES/NO/N/A | all rows | Records whether the partner-centroid substitution switch was enabled for Fight calculations. It is provenance, not a count. | `YES` |
| `social_disappearance_imputed_frames` | integer frames or blank | fight | Number of focal-animal qualifying disappearance frames for which a finite partner centroid was actually copied. Zero can legitimately mean the switch was off or no qualifying run occurred. | `8` |
| `remaining_missing_coordinate_frames_after_social_substitution` | integer frames | all rows | Original full-window missing frames minus actual copied frames. It is the remaining unusable coordinate-frame count for effective distance/location calculations. | `847` |
| `coordinate_frames_used_in_distance_and_location_calculations` | integer frames | all rows | Effective finite coordinate frames used after any enabled social substitution. | `6354` |

The copied partner position is not used to repair the raw latency baseline or
to pretend that the missing animal's independent path was observed. Its use is
explicitly recorded because it is an inference.

## Full-window provisional turtling screen

This is a centroid-path candidate detector, not a posture classifier. A student
must not rename these columns to “time upside down” without independent video
validation.

For fights, candidate frames on the fungus ROI are removed from the numerator.
Those detected fungus frames remain in the proportion denominator because they
are real biological time during which the animal is not counted as turtling.

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `turtling_candidate_frames` | integer frames | all rows | Frames belonging to at least one qualifying tight-loop sliding window after fight-only fungus exclusion. | `240` |
| `turtling_candidate_proportion_of_detected_frames` | proportion | all rows with detected frames | Candidate frames divided by original valid detected-coordinate frames in the approved analysis window. | `0.0338` |
| `turtling_candidate_events` | integer events | all rows | Number of contiguous runs of candidate frames. Separate runs are not merged across gaps. | `2` |
| `turtling_detector_status` | categorical text | all rows | Explicit provisional/calculated or unavailable detector status. | `CALCULATED_PROVISIONAL_CENTROID_PATH_CANDIDATES` |
| `turtling_window_frames` | integer observations/windows | all rows | Sliding detector window length. Current default: 120 frames. | `120` |
| `turtling_min_path_px` | numeric px | all rows | Minimum within-window accepted path after sub-pixel jitter steps are excluded. | `120` |
| `turtling_max_radius90_px` | numeric px | all rows | Maximum allowed 90th-percentile radius from the window's median centroid. Smaller values require tighter circling. | `35` |
| `turtling_min_turn_rotations` | numeric complete rotations | all rows | Minimum cumulative absolute wrapped turning, divided by `2π`, required in a candidate window. | `3` |
| `turtling_max_straightness` | proportion | all rows | Maximum net displacement divided by path length. Lower values require the animal to finish near where the looping path began. | `0.25` |
| `turtling_max_step_px` | numeric px | all rows | Maximum adjacent step permitted inside a candidate turtling window. This is separate from the broad 200-pixel artifact threshold. | `20` |

## Baseline, coordinate completeness, result interpretation, and source provenance

| Column | Type / units | Applies | Definition and interpretation | Example |
|---|---|---|---|---|
| `baseline_x_px` | numeric x px or blank | all rows | Original focal-animal x centroid at the exact approved analysis start. Blank when that exact coordinate is missing. | `412.6` |
| `baseline_y_px` | numeric y px or blank | all rows | Original focal-animal y centroid at the exact approved analysis start. Blank when that exact coordinate is missing. | `287.1` |
| `valid_coordinate_frames_in_window` | integer frames | all rows | Original IDtracker frames with finite x and y in the approved analysis window, before social substitution. | `6346` |
| `missing_coordinate_frames_in_window` | integer frames | all rows | Original IDtracker frames missing x or y in the approved window. With a 7201-observation window, valid plus missing should equal 7201. | `855` |
| `result_status` | categorical text | all rows | Overall latency-result interpretation, commonly `OK`, `THRESHOLD_NOT_REACHED`, or `NOT_CALCULATED` for a missing exact baseline. It does not replace specialized ROI/social statuses. | `OK` |
| `warning` | free text | all rows | Concatenated scientific/QC explanations: raw fallback, missing frames, excluded steps, social substitution, partition failures, or provisional turtling. Preserve this field in audits. | `RAW_IDTRACKER_INPUT: ...` |
| `trajectory_source_kind` | categorical text | all rows | Exact selected trajectory-source category. Priority is validated, without-gaps, legacy without-gaps, then explicit raw fallback. | `IDTRACKER_RAW_NPY` |
| `session_folder` | remote path text | all rows | Canonical IDtracker session folder used for ROI geometry and provenance. | `/data/labs/.../session_Camera_..._A3` |
| `trajectory_file` | remote path text | all rows | Exact trajectory file read for this calculation. This distinguishes validated/without-gaps/raw sources. | `/data/labs/.../trajectories/trajectories.npy` |
| `archived_original_start_frame` | integer global frame | all rows | Start value before an approved later change. If no change occurred, it normally equals the final start. It is intentionally placed near the end as provenance rather than the primary analysis variable. | `760` |
| `start_frame_decision_source` | categorical text | all rows | How the final start was established: source interval, manual GUI/CSV entry, approved Jump Audit, or restored prior decision. | `JUMP_AUDIT_APPROVED` |
| `start_frame_decision_provenance` | free text | all rows | Human/audit explanation for an approved start change, including prior start and evidence where available. Blank can mean no adjustment narrative was required. | `Approved video-wide disturbance recommendation; previous start=760; final start=1050; ...` |

### Trajectory source categories

| Value | Meaning |
|---|---|
| `IDTRACKER_VALIDATED` | `validated.npy`; highest recognized priority. |
| `IDTRACKER_WITHOUT_GAPS` | IDtracker `without_gaps.npy`. |
| `IDTRACKER_LEGACY_WO_GAPS` | Legacy `trajectories_wo_gaps.npy`. |
| `IDTRACKER_LEGACY_WITHOUT_GAPS` | Legacy `trajectories_without_gaps.npy`. |
| `IDTRACKER_RAW_NPY` | Raw `trajectories.npy` fallback; missing coordinates remain visible. |
| `IDTRACKER_RAW_H5` | Raw `trajectories.h5` fallback. |
| `IDTRACKER_RAW_CSV` | Raw `trajectories.csv` fallback. |

## Recommended student-facing analysis names

Do not rename the source CSV in place. In a derived R table, short display
labels may be created while retaining the original columns. Recommended
labels include:

| Source column | Suggested plot/table label |
|---|---|
| `latency_to_threshold_frames` | Provisional latency to 30-px displacement (frames) |
| `post_wake_distance_px_per_valid_step` | Wake-through-end distance per valid step (px/step) |
| `post_wake_3600_distance_px_per_valid_step` | Fixed post-wake distance per valid step (px/step) |
| `post_wake_3600_open_area_proportion` | Fixed post-wake open-area proportion |
| `post_wake_3600_open_distance_px_per_available_step` | Fixed open distance per available step |
| `post_wake_3600_speed_px_per_open_step` | Fixed speed conditional on open steps |
| `post_wake_3600_off_fungus_proportion` | Fixed off-fungus proportion |
| `post_wake_3600_frames_within_social_distance` | Fixed frames within social threshold |
| `turtling_candidate_proportion_of_detected_frames` | Provisional turtling-candidate proportion |

The word **provisional** should remain attached to wake and turtling variables
until the biological definitions are independently validated.

## Final caution

This dictionary explains what the software calculated. It does not by itself
establish that a variable is biologically valid for a particular hypothesis.
Before formal analysis, confirm:

- the intended analysis window;
- the relevant status is usable;
- the numerator and denominator answer the same question;
- missingness and raw-fallback provenance are acceptable;
- Fight rows retain their paired session structure; and
- all exclusions and joins have explicit sample-size audits.
