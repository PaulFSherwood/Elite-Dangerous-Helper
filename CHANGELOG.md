# Changelog

Notable user-facing and project-maintenance changes are recorded here.

## v3.2.8 — 2026-09-19

### Repository and release cleanup

- Kept `ed_journal_probe.py` at the repository/install root so existing shortcuts and launch commands continue to work.
- Moved the rest of the runtime Python implementation into `src/elite_journal_helper/`.
- Added a single authoritative application version under the package and `--version` support to the compatibility launcher.
- Reorganized install/uninstall/release helpers under `scripts/` and project documentation under `docs/`.
- Added runtime/development requirement files, GitHub Actions tests, and a repeatable release-check script.
- Expanded `.gitignore` so caches, backups, local patches, runtime databases, and editor files do not clutter the repository.
- Removed the unused legacy SQLite module and tracked development database.
- Kept `assets/`, `data/`, and `styles/` in their established locations so existing resource layouts do not need another migration.
- Updated tests and release tooling for the `src/` package layout.

## v3.2.7 — 2026-09-19

- Made the Construction Overview responsive at narrow window widths.
- Prevented Primary/Secondary/Scope/Next/Logistics summary text from overlapping.

## v3.2.6 — 2026-09-18

- Added Mini Mode `STOCK` for the displayed commodity using ship + carrier inventory.

## v3.2.5 — 2026-09-18

- Added right-click commodity pinning so a chosen construction material can be shown in Mini Mode.

## v3.2.4 — 2026-09-15

- Made startup profiling opt-in with `--profile-startup`.

## v3.2.3 — 2026-09-15

- Reduced Construction startup/render cost by avoiding repeated catalog and build-state calculations.

## v3.2.1–v3.2.2 — 2026-09-15

- Moved expensive journal-history work off the pre-window startup path.
- Added visible startup feedback and targeted startup profiling.
- Improved Construction Overview readability.

## v3.2.0 — 2026-09-15

- Improved Construction edit/cancel performance and compact-window layout behavior.
