# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). While the version is 0.x, a MINOR version can change
how checks decide. A change to a rule or a number in docs/spec.md always raises the MINOR version
and the spec version.

## [Unreleased]

## [0.1.1] - 2026-11-15

### Fixed

- Newton: a run no longer stops with an IndexError on an asset whose last joint is a fixed joint,
  such as a gripper with fingertips fixed to its fingers. A fixed joint has no position in Newton,
  and the engine read one for it.

## [0.1.0] - 2026-11-15

The first release. The checks follow docs/spec.md, version 0.2.

### Added

- The checks LOAD, DROP, HOLD, TRACK, LIMIT, STABLE, SPEED, PASSIVE, GRIP and SHAKE.
- Wheeled robots: STAND, DRIVE, TURN and STEER, and joint checks with the base held up.
  They read the robot's wheels from SimReady_Metadata.mobile (docs/wheeled-robots.md).
- A USD reader for packages from any maker, in SI units.
- A plan that decides which checks apply to an asset, the same way for every engine.
- results.json with a JSON Schema.
- The `proofmass-check` command: `run` and `list-checks`.
- Engines: PhysX in Isaac Sim 6.1, and Newton as an experiment.

[Unreleased]: https://github.com/proofmass/proofmass-check/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/proofmass/proofmass-check/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/proofmass/proofmass-check/releases/tag/v0.1.0
