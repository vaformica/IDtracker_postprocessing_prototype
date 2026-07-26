# Changelog

All notable changes to this standalone scientific prototype are documented
here. Versions use semantic versioning while the software remains independent
from the production IDtracker pipeline.

## 0.8.1 - 2026-07-25

- Added rapid post-processing PDF review controls modeled after the old QC GUI:
  **Start rapid review**, spacebar opens the cached local PDF, `A` approves, and
  `R` marks the newest run for IDtracker rerun.
- Rapid `A` and `R` decisions advance automatically to the next unreviewed
  processed newest run and open its cached PDF. The mouse rerun button still
  asks for a detailed reason; rapid `R` writes a standard reason for speed.
- Added a QC export package under
  `~/Downloads/IDtracker_postprocessing_results/postprocessing_qc/` containing
  timestamped approved-results CSV, rerun-report CSV, and copies of approved
  PDFs in `approved_pdfs/`.
- Indexed the completed local `pdfs/` folder after automatic download so QC
  review opens local cached PDFs instead of repeatedly looking up remote files.

## 0.8.0 - 2026-07-25

- Created the reversible `feature/postprocessing-qc-review` development branch
  from the tagged v0.7.2 checkpoint.
- Replaced the old `QC/run_status.csv` approval gate with recursive discovery
  of every supported IDtracker session and run-metadata link under one or more
  researcher-entered Firebird roots.
- Kept IDtracker execution and post-processing review as separate QC layers.
  Old pipeline decisions are not read as approval evidence.
- Retained every repeated run, grouped exact video/cell/analysis keys, and
  deterministically ranked the newest run while displaying older runs in a
  dedicated Duplicates tab.
- Added explicit `IDENTITY_INCOMPLETE` handling for bare sessions whose
  `session.json` cannot supply a cell. Such sessions are retained but never
  processed under a guessed identity.
- Added canonical `session.json:video_paths[0]` fallback when linked run
  metadata has a blank video, while rejecting malformed cell labels that do
  not match an uppercase letter followed by digits.
- Added a Post-processing QC tab with append-only `UNREVIEWED`, `APPROVED`, and
  `RERUN` decisions, mandatory rerun reasons, reversible unreview actions, and
  PDF-opening/report-download controls.
- Added Firebird QC ledgers and atomic derived files:
  `postprocessing_qc_decision_history.csv`,
  `postprocessing_qc_current.csv`, `approved_results_latest.csv`, and
  `sessions_marked_rerun_latest.csv`.
- Rebuilds the approved data from current rank-1 approvals instead of blindly
  appending. An approval is not transferred when a newer duplicate appears.
- Added eight `postprocessing_qc_*` provenance columns to the 173-column
  approved-results schema; the ordinary completed-batch schema remains 165
  columns.
- Added a large first-page PDF missing-coordinate banner showing, for every
  animal, missing frames, inclusive observations, and percentage. Full video
  and cell identity remain at the top of every PDF page.
- Added recursive discovery, duplicate ranking, latest-decision, stale
  approval, approved-file rebuild, rerun-report, search-root, and PDF-banner
  tests.

## 0.7.2 - 2026-07-25

- Rewrote the beginning of the README as a student-facing guide explaining
  purpose, scope, history, provenance, scientific cautions, row grain, units,
  core geometry, worked BA/fight examples, and a downstream-analysis
  checklist.
- Added `DATA_DICTIONARY.md`, with a detailed definition, units/type,
  applicability, and example for every one of the 165 fields in a combined
  results CSV.
- Added explicit explanations of frames versus intervals versus movement
  steps, blank versus zero, status fields, midpoint ROI assignment, jump
  rejection, social-disappearance substitution, fixed versus variable
  post-wake windows, and provisional turtling.
- Centralized the combined CSV leading and trailing metadata field lists and
  added an automated test that prevents undocumented schema fields from being
  introduced.
- Included the data dictionary in the Firebird installation copy.
- Scientific calculations, the 165-field combined output schema, and PDF
  content are unchanged from v0.7.1.

## 0.7.1 - 2026-07-25

- Replaced recursive PDF-folder transfer with one atomic, uncompressed ZIP
  archive built on Firebird. PDFs are already compressed, so stored ZIP avoids
  unnecessary compression time while removing per-file network overhead.
- Added safe Mac extraction that accepts only flat `.pdf` members, verifies the
  Firebird-reported PDF count, and removes the temporary archive before the
  hidden completed-run folder is promoted.
- Moved the final chime and popup from remote-processing completion to verified
  Mac-download completion. The popup now reports the completed local folder
  and extracted PDF count.
- Added explicit download-failure state handling without promoting partial
  results.
- Added a dedicated **Results & Downloads** tab and moved both manual recovery
  download buttons there.
- Reflowed Sessions and Jump Audit action buttons across multiple rows and
  reduced the default/minimum window widths for laptop displays.
- Added archive creation, extraction, count-mismatch, and unsafe-member tests.
- Scientific calculations and the v0.7.0 output schema are unchanged.

## 0.7.0 - 2026-07-25

- Retained every existing variable-length `post_wake_*` output from wake
  through the approved inclusive analysis end.
- Added a separately grouped `post_wake_3600_*` block covering exactly 3600
  adjacent-frame intervals and 3601 inclusive coordinate observations.
- Anchored BA fixed windows at each focal animal's wake threshold crossing.
  Anchored both rows of a two-animal fight at the later of the two crossings,
  so both animals are compared over one common range after both have awakened.
- Required a complete fixed window. Missing wake crossings, unexpected fight
  animal counts, and fixed ends beyond the approved analysis end produce
  explicit statuses and blank numeric results rather than zeros or shortened
  windows.
- Reused the v0.6.0 accepted-step, missing-gap, 200-pixel anti-jump,
  segment-midpoint, wall, fungus, and direct joint-mask rules and assertions.
- Added fixed-window social contact, animal-specific social movement,
  disappearance, visible return-interaction, optional substitution,
  remaining-missing, and effective-coordinate outputs.
- Added fixed-window provisional turtling frame, event, proportion, and status
  outputs. Fight time on fungus remains in the detected-frame denominator
  while fungus candidates remain excluded from the numerator.
- Left the PDF generator unchanged.

## 0.6.0 - 2026-07-24

- Kept the researcher-selected one-frame jump threshold at 200 pixels.
  Adjacent steps exactly equal to 200 pixels are accepted; steps strictly
  greater are rejected.
- Reworked jump handling as step-level QC. A rejected adjacent step is omitted
  from latency chains, distance totals, ROI movement distances, social
  movement distance, and PDF path connections, while both endpoint coordinates
  remain available for frame-based wall/fungus counts.
- Added `one_frame_jump_threshold_px` and `one_frame_jumps_excluded`. Retained
  `jump_threshold_px` as a compatibility alias and the deprecated
  `jump_artifact_coordinate_frames_excluded` as zero because coordinates are
  no longer deleted.
- Added post-wake calculations from the provisional threshold-crossing frame
  through the inclusive analysis end. The core adjusted distance denominator
  is valid adjacent movement steps, not elapsed frames.
- Added post-wake wall/open frame, step, distance, opportunity-adjusted, and
  conditional-speed outputs using the existing centroid and segment-midpoint
  geometry.
- Added fight-only post-wake fungus on/off outputs and direct
  open-and-off-fungus intersection outputs. BA fungus/joint numerics are blank
  with explicit not-applicable statuses.
- Added explicit unavailable statuses and blank numeric outputs when the exact
  baseline is invalid, wake is not reached, or no valid post-wake movement
  opportunity exists.
- Updated PDF jump marks and metadata to describe rejected steps rather than
  deleted coordinate frames.
- Added runtime partition assertions and representative BA, fight, missing-gap,
  rejected-jump, invalid-baseline, and threshold-not-reached tests.

## 0.5.6 - 2026-07-24

- Added **Load previous settings or results** and
  **Save current settings and decisions** controls at the top of Setup & Run.
- Added versioned JSON settings bundles containing visible GUI parameters,
  positive start decisions with archived originals and provenance, and current
  Jump Audit summary/track tables.
- Added direct restoration from existing combined-results CSV files and Jump
  Audit video CSV files, including automatic sibling track-table loading.
- Separately loaded Jump Audit decisions supplement previously queued combined
  CSV decisions, so loading the detailed audit cannot discard session starts.
- Saved decisions may be loaded before scanning and are applied afterward only
  to the newly resolved authoritative approved-session table.
- Matching uses exact QC record ID first, then exact
  `(video, cell, analysis)` when an approved run has changed. Conflicts reject
  the restoration; unmatched decisions are explicitly logged.
- Only Jump Audit rows already marked `APPROVED` restore video-wide starts.
  Pending recommendations remain display-only.
- Restored decisions retain prior provenance and append the settings filename
  and restoration timestamp.

## 0.5.5 - 2026-07-24

- Changed the researcher-selected provisional one-frame jump threshold default
  from 50 to 200 pixels in the GUI, processor API, CLI, CSV/PDF provenance, and
  methods documentation.
- Corrected non-returning jump handling so one discontinuity no longer erases
  the remainder of the analysis window. The jump-destination coordinate is
  excluded, no distance is bridged across it, and later finite coordinates
  resume as a new unconnected segment.
- Added the explicit
  `JUMP_DISCONTINUITY_EXCLUDED_TRACK_RESUMED_REVIEW` status and warning because
  resumed geometry cannot by itself confirm retained biological identity.
- Preserved the existing returning-excursion rule: all coordinates from the
  jump destination through the frame before return remain excluded.

## 0.5.4 - 2026-07-24

- Added the processing-batch date and time to the automatically downloaded CSV
  filename: `combined_results_YYYYMMDD_HHMMSS_microseconds.csv`.
- The CSV filename timestamp now exactly matches its enclosing
  `completed_run_YYYYMMDD_HHMMSS_microseconds/` folder.

## 0.5.3 - 2026-07-24

- Clarified automatic Mac downloads: every successful run creates
  `completed_run_YYYYMMDD_HHMMSS_microseconds/` under
  `~/Downloads/IDtracker_postprocessing_results/`.
- Each completed-run folder contains the matching `combined_results.csv` and
  `pdfs/` collection; the entire folder is promoted atomically from a hidden
  partial folder only after both downloads finish.

## 0.5.2 - 2026-07-24

- Fixed Jump Audit omission of videos deliberately marked for manual start
  review. The read-only audit may now use one positive, unambiguous detected
  interval as provisional timing evidence.
- Kept processing conservative: a provisionally audited detected start does
  not become final until the researcher approves the video recommendation.
- Added explicit audit-report provenance identifying records that used a
  detected interval for audit only. Zero, missing, and conflicting detected
  starts remain excluded.

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
