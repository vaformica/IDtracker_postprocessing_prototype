# Repository status

This repository is the standalone IDtracker post-processing prototype.

- It is intentionally separate from the existing production/QC pipeline.
- It does not replace, import, or modify the production post-processing code.
- A later, explicitly reviewed change may merge selected work into the larger
  pipeline.
- Scientific output files, downloaded PDFs, local environments, and caches are
  excluded from version control.

## Version history

- `v0.1.0` preserves the initial tested standalone snapshot.
- `v0.1.1` adds offline-readable mathematical notation and establishes the
  explicit standalone version/changelog files.
- `v0.2.0` adds explicit remaining-missing and video-year columns plus the
  provisional, review-required tight-loop turtling candidate detector.

The automated suite contains 28 tests. Firebird execution remains a separate
validation step and is not implied by local test success.
