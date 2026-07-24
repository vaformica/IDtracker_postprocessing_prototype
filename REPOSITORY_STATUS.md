# Repository status

This repository is the standalone IDtracker post-processing prototype.

- It is intentionally separate from the existing production/QC pipeline.
- It does not replace or modify the old post-processing code.
- A later, explicitly reviewed change may merge selected work into the larger
  pipeline.
- Scientific output files, downloaded PDFs, local environments, and caches are
  excluded from version control.

## Initial preserved state

The initial repository snapshot contains the tested prototype for scanning
approved sessions, processing frame- and pixel-based measurements, exporting
combined CSV results and diagnostic PDFs, and documenting the calculations in
`METHODS.html`.

Before this snapshot was made, the automated test suite completed successfully
with 26 passing tests.
