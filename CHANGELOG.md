# Changelog

All notable changes to CiteLadder are documented in this file. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) when it begins publishing releases.

## [Unreleased]

### Added

- Weekly Dependabot coverage for backend `uv`, frontend `pnpm`, Docker, and GitHub Actions
  dependencies. Patch and minor updates are grouped; major updates remain separate for review.
- A clean-clone Compose workflow that starts the frontend, API, migrations, database, and workers.
- A pre-release checklist in [`docs/release-checklist.md`](docs/release-checklist.md).

### Changed

- Active documentation now identifies `docs/site-health.md` as the Site Health authority instead
  of linking to a removed archive directory.

## Release policy

Do not create a tag, GitHub release, or package publication from this unreleased entry. A release
is created only after the checklist passes on a clean checkout and the intended version, release
notes, and commit are approved.
