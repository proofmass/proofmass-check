# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). While the version is 0.x, a MINOR version can change
how checks decide. A change to a rule or a number in docs/spec.md always raises the MINOR version
and the spec version.

## [Unreleased]

### Added

- The checks LOAD, DROP, HOLD, TRACK, LIMIT, STABLE, SPEED, PASSIVE, GRIP and SHAKE (spec 0.1).
- Wheeled robots: STAND, DRIVE, TURN and STEER, and joint checks with the base held up (spec 0.2).
  They read the robot's wheels from SimReady_Metadata.mobile (docs/wheeled-robots.md).
- A USD reader for packages from any maker, in SI units.
- A plan that decides which checks apply to an asset, the same way for every engine.
- results.json with a JSON Schema.
- The `proofmass-check` command: `run` and `list-checks`.
- Engines: PhysX in Isaac Sim 6.1, and Newton as an experiment.
