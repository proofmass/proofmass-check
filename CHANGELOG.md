# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). While the version is 0.x, a MINOR version can change
how checks decide. A change to a rule or a number in docs/spec.md always raises the MINOR version
and the spec version.

## [Unreleased]

### Added

- `proofmass-check gui`: a page in the browser that shows results files, phase 1 of
  [docs/gui.md](docs/gui.md). It opens folders and finds every results file below them, whatever
  its name. It shows a matrix of runs and checks, the page of one run, a comparison of runs (PhysX
  and Newton, two versions, repeats), and a comparison of two folders paired by the asset's SHA-256.
  It saves a report as one HTML file or as CSV. It never changes an asset or a results file. The
  server listens on 127.0.0.1 only and needs the token from the address it prints. It needs
  nothing beyond the standard library.
- The GUI runs checks too, phase 2 of docs/gui.md. Settings keep the Python of each engine and a
  workspace. A new batch lists the USD files of a folder, takes the engines, the Newton repeats and
  the settings, and shows the command of each run before it starts. The batch's page shows each
  asset of each run live: the check, its step and the time so far. Runs go one at a time, and a run
  can be cancelled. When a worker crashes in the middle of an asset, that asset is marked as
  stopped and a new worker runs the rest. The GUI reads the state of a batch from its files, so it
  can read it again after a restart. It never accepts the NVIDIA licence for the user.
- `proofmass-check run` takes several assets, and runs them in one start of the engine. Isaac Sim
  can take a minute to start, and it started once per asset before. With several assets, `--out`
  is a folder with a folder per asset. An asset that stops with an error does not stop the others.
  The exit status is the highest of the assets'. Two assets of one file name are refused.
- `proofmass-check run --events FILE`: the progress as JSON Lines, for a program that follows a
  run: the engine's start, each asset, each check with its engine operations, each verdict, the
  end (docs/gui.md, section 5.2). `runner.run_checks()` takes the callback that writes them.
- `measurements` in `results.json`: each check that ran lists the numbers it compared with its
  rule, each with its limit, bound, unit and `ok` (docs/spec.md, section 6). A program can now read
  them without the detail text, whose wording can change. The GUI uses them for the margin of each
  joint. It is a new optional field, so `schema_version` stays 1. The verdicts and the detail text
  do not change.

### Changed

- `checks.wheeled.evaluate()` gives the measurements too: (ok, detail, measurements).

## [0.2.0] - 2026-11-18

The checks follow docs/spec.md, version 0.3.

### Added

- Newton: a joint without PhysicsDriveAPI takes its drive from an `MjcActuator`, by the rule
  Newton uses (docs/spec.md, "Reading the asset"). A package whose MuJoCo physics layer drives its
  joints only with actuators had "no position drive" before, and HOLD, TRACK, LIMIT, STABLE and
  GRIP did not run on it in Newton. PhysX does not read an `MjcActuator`, so in PhysX such a joint
  still has no drive.

### Changed

- An engine says whether it reads `MjcActuator`: `reads_mjc_actuators` in the `Engine` protocol.
  An engine outside this package needs it too.

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

[Unreleased]: https://github.com/proofmass/proofmass-check/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/proofmass/proofmass-check/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/proofmass/proofmass-check/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/proofmass/proofmass-check/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/proofmass/proofmass-check/releases/tag/v0.1.0
