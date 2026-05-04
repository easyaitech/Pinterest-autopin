# Changelog

## [1.3.1] - 2026-05-04

### Added

- Name the dedicated Pinterest Chrome profile `Pinterest AutoPin` during profile initialization, making it easier to distinguish from personal Chrome profiles.

### Fixed

- Preserve existing Chrome profile metadata while applying the display name.
- Skip display-name refresh while the dedicated Chrome profile is open, including Chrome singleton symlink cases.
