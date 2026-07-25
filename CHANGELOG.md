# Changelog

All notable changes to this standalone scientific prototype are documented
here. Versions use semantic versioning while the software remains independent
from the production IDtracker pipeline.

## 0.5.1 - 2026-07-24

- Restored one-folder automatic downloads on the Mac. Each completed run now
  creates `results_YYYYMMDD_HHMMSS_microseconds/` containing
  `combined_results.csv` and `pdfs/`.
- Stages the entire timestamped folder under a hidden `.partial` name and
  promotes it only after both the CSV and matching PDF collection download
  successfully.

## 0.5.0 - 2026-07-24

- Added a GUI-configurable coordinate-jump threshold, default 50 pixels.
- Added a 120-frame return search. Returning relocation excursions are excluded
  coordinate-by-coordinate; a jump with no return causes the remainder of the
  analysis window to be conservatively excluded and flagged for start review.
- Excluded jump-artifact coordinates from latency, total distance, wall,
  fungus, social, and turtling calculations without modifying raw files or
  adding interpolation. Steps exactly equal to 50 pixels remain accepted.
- Added concise `jump_threshold_px`,
  `jump_artifact_coordinate_frames_excluded`, and `jump_qc_status` columns.
- Prevented jump-QC exclusions from being misclassified or copied as social
  disappearance; the effective social-substitution series is jump-checked
  again after copying.
- Added a separate GUI Jump Audit tab covering all approved ready BA and fight
  sessions. Video-wide evidence requires at least three distinct approved
  sessions and at least half of the available sessions for that video.
- Added reviewable starts rounded to the next 50-frame boundary after the final
  synchronized disturbance, with an explicit per-video approval button.
- Added timestamped video- and track-level Jump Audit CSV reports.
- Renamed the main analysis columns to intuitive final-decision names:
  `analysis_start_frame` and `analysis_end_frame_inclusive`. Original starts
  and approval explanations are archived near the end in three provenance
  columns.
- Required latency crossings to remain connected to the exact analysis-start
  coordinate by uninterrupted valid steps at or below the anti-jump threshold;
  this prevents an IDtracker relocation from creating a false wake latency.
- Broke 2-D, 3-D, social, and buffer-map PDF paths at rejected jumps instead of
  drawing impossible straight lines. Rejected raw jump endpoints appear as
  subtle gray marks on the primary 2-D audit pages.
- Preserved raw coordinates. PDF tracks use the cleaned working series and
  show excluded raw coordinates as subtle gray x marks.

## 0.4.0 - 2026-07-24

- Added a GUI-selectable SLURM job-array execution mode for large approved
  batches; it is now the default execution mode.
- Added editable SLURM maximum concurrency, account, partition, time, and
  memory controls. Defaults are 20 simultaneous tasks, account `swat`, the
  cluster's default partition, two hours, one CPU, and 4 GB per session.
- Added one manifest-driven worker per selected ready session and a dependent
  `afterany` finalizer job that audits all task outcomes and refuses promotion
  unless every task succeeded.
- Added per-task status JSON and SLURM stdout/stderr logs under the timestamped
  remote batch folder.
- Preserved the previously complete combined CSV and PDF folder unless all
  array tasks succeed, all expected files are verified, combination succeeds,
  and the finalizer atomically promotes the batch.
- Added GUI polling of SLURM progress, explicit array/finalizer job IDs in the
  log, and the completion chime/popup only after successful final promotion.
- Retained direct SSH processing as an explicitly labeled small-test fallback.
- Added `processing_execution_mode` to the combined CSV provenance fields.
- Added **Check all filtered ready sessions** and **Uncheck all sessions**
  controls so large approved subsets can be selected without hundreds of
  double-clicks.

## 0.3.0 - 2026-07-24

- Added a completion chime and popup that appears only after the complete CSV
  and PDF batch has been promoted successfully.
- Moved `Process checked sessions` to the Sessions tab.
- Added `script_version` to every per-session and combined CSV row and to the
  final PDF metadata page.
- Excluded fight turtling-candidate frames on or inside the secondary fungus
  ROI from candidate counts, proportions, events, and PDF overlays.
- Added `turtling_candidate_proportion_of_detected_frames`, defined as the
  fungus-excluded candidate-frame count divided by original valid detected
  coordinate frames for that animal in the inclusive analysis window.
- Clarified that `social_disappearance_imputed_frames` records actual
  partner-centroid substitutions and is expected to be zero when the optional
  substitution switch is off.
- Changed the GUI default so social-disappearance substitution is checked
  (ON), while retaining explicit per-row provenance and allowing the user to
  turn it off before processing.

## 0.2.0 - 2026-07-24

- Added the direct
  `remaining_missing_coordinate_frames_after_social_substitution` audit
  column.
- Added `video_year` as the fourth combined-CSV column for recognized 2025 and
  2026 recording dates, including prefixed legacy video names.
- Added a GUI-configurable, provisional tight-loop turtling candidate detector
  for both BA and fight analyses.
- Added per-animal candidate frame/event counts and complete detector-threshold
  provenance to the CSV.
- Added thin, semi-transparent dark-red dashed turtling-candidate paths to the
  2-D and 3-D PDF plots and documented the rule on the final metadata page.
- Documented the detector's equations, calibration limitations, missing-data
  policy, and posture-classification warning.

## 0.1.1 - 2026-07-24

- Rendered the optional social-disappearance coordinate-substitution equation
  directly in HTML so mathematical notation remains readable without MathJax
  or an internet connection.
- Established explicit standalone version and changelog files.
- Corrected repository-location documentation.

## 0.1.0 - 2026-07-24

- Preserved the initial tested standalone prototype.
- Added recursive discovery of authoritative approved QC sessions on Firebird.
- Added inclusive, global-frame analysis windows and displacement latency.
- Added analysis-window distance, wall-buffer, fungus, and social-distance
  summaries with explicit additivity and missing-data diagnostics.
- Added optional, default-off social-disappearance partner-centroid
  substitution for distance and location calculations.
- Added timestamped combined CSV and PDF downloads on the Mac.
- Added multipage scientific audit PDFs and mathematical methods documentation.
- Added automated regression tests; the preserved baseline passed 26 tests.
