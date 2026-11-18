# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). While the version is 0.x, a MINOR version can change
how checks decide. A change to a rule or a number in docs/spec.md always raises the MINOR version
and the spec version.

## [Unreleased]

### Added

- The reader takes the drive of a joint from an `MjcActuator` when the joint has no
  PhysicsDriveAPI, by the rule Newton uses (docs/spec.md, "Reading the asset"). A package whose
  MuJoCo physics layer drives its joints only with actuators had "no position drive" before, and
  HOLD, TRACK, LIMIT, STABLE and GRIP did not run on it in Newton.
  
### Fixed

- Newton: one move that ended in NaN no longer gives NaN in every move after it. The MuJoCo Warp
  solver keeps some data from step to step, and the engine's reset did not clear it. On AgiBot's
  G2, LIMIT and PASSIVE gave NaN for every joint after one TRACK move that ended in NaN.
- Newton: the first move of a run (DROP or HOLD) and the first load of GRIP at each grip site now
  last as long as the spec says. The engine records its steps as a CUDA graph the first time it
  runs them, and it counted the recorded steps as steps that had run. Recording does not run them,
  so that move was 50 steps (0.1 s) short. Results of DROP, HOLD and GRIP can change a little.
- Newton: a measurement that runs out of MuJoCo Warp's buffer for constraints or for contacts now
  runs again with that buffer twice as large. The buffers start at Newton's own sizes, which can be
  too small for a large robot (64 constraint rows and 48 contacts on AgiBot's G2), and MuJoCo Warp
  leaves out what does not fit. On G2, two TRACK moves of the arms ended in NaN for that reason.

## [0.1.2] - 2026-11-16

### Fixed

- PhysX: every test now starts with each joint at its rest position, as the file has it. Isaac Sim
  reset a PhysX mimic follower to 0. On a gripper whose 0 is the closed end, that finger started
  inside the grip box and pushed it away, so GRIP and SHAKE measured a box that was no longer at
  the grasp centre. Results of GRIP, SHAKE and SPEED can change for an asset with a mimic joint
  whose rest position is not 0.

### Changed

- SPEED: when a joint was faster in the first 5 steps, which the check does not measure, than
  after them, the result gives that speed too. A short joint such as a gripper finger ends its
  move in those steps, and the result showed only the speed of a joint that already stood. The
  rule and the verdicts are as before.

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

[Unreleased]: https://github.com/proofmass/proofmass-check/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/proofmass/proofmass-check/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/proofmass/proofmass-check/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/proofmass/proofmass-check/releases/tag/v0.1.0
