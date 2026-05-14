# Changelog

## [1.4.0] - 2026-05-14

### Added

- Publish Pinterest carousel Pins from `images[]` payloads through the CLI, Playwright automation, and Feishu worker.
- Route multi-image publishing through Pinterest Ads Manager's Pin builder for business carousel creation.
- Support per-image final attachments and alt text when publishing approved Feishu records.

### Fixed

- Fail carousel publishing when Pinterest does not expose the carousel type selector instead of continuing in the wrong Pin format.
- Require the published carousel URL to match the current Pin title before marking a record as published.

## [1.3.1] - 2026-05-04

### Added

- Name the dedicated Pinterest Chrome profile `Pinterest AutoPin` during profile initialization, making it easier to distinguish from personal Chrome profiles.

### Fixed

- Preserve existing Chrome profile metadata while applying the display name.
- Skip display-name refresh while the dedicated Chrome profile is open, including Chrome singleton symlink cases.
