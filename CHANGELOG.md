# Changelog

All notable changes to this standalone scientific prototype are documented
here. Versions use semantic versioning while the software remains independent
from the production IDtracker pipeline.

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
