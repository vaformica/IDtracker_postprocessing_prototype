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

The automated suite contains 26 tests. Firebird execution remains a separate
validation step and is not implied by local test success.
