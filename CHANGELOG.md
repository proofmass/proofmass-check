# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). While the version is 0.x, a MINOR version can change
how checks decide. A change to a rule or a number in docs/spec.md always raises the MINOR version
and the spec version.

## [Unreleased]

### Changed

- Spec 0.4: an asset fixed to the world gets no floor. None of its checks needs one, and an arm in
  its file pose can reach through it: a UR5e's wrist is 19 mm above it, 0.8 m out, so its shoulder
  touched the floor 1.6 deg into TRACK and failed by 178.6 deg, and a Fanuc CRX-10iA/L failed by
  31 deg. Without the floor both pass every check. Results of spec 0.3 and 0.4 are not compared.

### Added

- `proofmass-check describe-wheels`: proposes `SimReady_Metadata.mobile` for a differential or
  skid-steer robot from its wheel joints and colliders, and with `--write` writes it in a layer next
  to the robot, so the wheeled checks run on a robot from another maker. inspect gives the same
  proposal in `derived_mobile`, and the GUI's inspector shows it with the command. For five robots
  that come with Isaac Sim 6.1 (Jetbot, Create 3, TurtleBot3, Jackal, Limo) it proposes the
  description with which PhysX ran their wheeled checks. It does not propose one for an Ackermann
  robot, whose steering range must come from its maker.

## [0.3.3] - 2026-11-25

The checks follow docs/spec.md, version 0.3. No rule or number changed. The reader now reads sphere
colliders, so on an asset that has them DROP and the floor height can differ from 0.3.2.

### Added

- A note when an asset's joints look like wheels (no limits, a near horizontal axis, a velocity drive)
  but its root layer has no `SimReady_Metadata.mobile`: the wheeled checks do not run on it. Five
  robots that come with Isaac Sim 6.1 (Jetbot, Create 3, TurtleBot3, Jackal, Limo) have none, and passed
  on LOAD and DROP alone. `results.json` lists the joints in `wheels_without_mobile`, a new optional
  field, and the GUI and the HTML report put "wheels not checked" next to the verdict.
- The column of each check in the GUI's matrix, and in the HTML report, says what the check does
  when the pointer rests on it: the check's title from the spec. The wheeled column lists its four.

### Fixed

- The reader reads sphere colliders (`UsdGeom.Sphere`), such as Jetbot's wheels and Create 3's ball
  caster. It skipped them, so DROP and the floor height did not see those parts. inspect gives them,
  and the 3D view draws them.
- Newton refuses a USD stage with composition errors, such as a referenced file that is missing. The
  run now stops with that message on one line, as for the solver's errors in 0.3.2, not a traceback.
- The 3D view stopped with "Maximum call stack size exceeded" on an asset whose colliders are full
  render meshes (Jetbot: 1.4 million triangles). Past 100 000 triangles it now leaves the hulls out and
  says so.

## [0.3.2] - 2026-11-24

The checks follow docs/spec.md, version 0.3. No rule, number or verdict changed.

### Changed

- The inspector's 3D view stays in sight: when the page scrolls past it, a smaller view docks in
  the bottom right corner and shows the joint picked in the tables below. Before, a pick in the
  joints table needed a scroll back up to see it.

### Fixed

- When Newton's MuJoCo solver cannot build an asset, the run stops with the solver's message as its
  error, not with a Python traceback that hides it at its end. On the Lightwheel assets: a rigid body
  with no joint (CoffeeMachine102), and a drive with `maxForce` 0 (Sink002).
- A Python whose Newton packages do not import, for example another version of `mujoco_warp`, now
  gives "the newton engine needs Newton ... in this Python" with the import error, as a Python
  without Newton does, instead of a traceback.

## [0.3.1] - 2026-11-23

The checks follow docs/spec.md, version 0.3. No rule or number changed, and no verdict changes: a
run says more about what its verdict covers.

### Added

- `engine_cannot_run` in `results.json`: the checks the asset needs that the engine cannot run
  yet, for example STAND, DRIVE and TURN of a wheeled robot in Newton, and a note that names them.
  Such a run could pass with only LOAD run. The GUI and the HTML report now put "N not run" next to
  its verdict, and say that a pass does not cover those checks. It is a new optional field, so
  `schema_version` stays 1.
- A note in every engine but PhysX for each joint with `physxJoint:jointFriction`, which only
  PhysX reads. Friction that holds a door still in PhysX does nothing in Newton, so PASSIVE can pass
  there (docs/spec.md, section 5).

### Changed

- HOLD marks a joint that fails with FAIL in its detail, as TRACK, LIMIT, PASSIVE and SPEED do, so
  the GUI and the report show which joint failed.
- DROP on an asset with no collider says "no collider to rest on the floor" instead of
  "lowest collider +inf mm from the floor".
- The HTML report that the GUI saves has the look of the reports on proofmass.com: the Proofmass
  logo, the counts of runs that passed, failed and stopped, and tables in Archivo and IBM Plex Mono.
  It still loads nothing: its CSS, fonts (latin letters only, 0.16 MB) and logo are in the file.
  Its settings read as in the GUI, the tolerances in mm and deg, and a margin is a percentage of
  the limit, as in the GUI. The logo is in one file, `gui/logo.svg`, for the page and the report.

## [0.3.0] - 2026-11-22

The checks follow docs/spec.md, version 0.3. No rule or number changed. The spec gained the
measurements of each check (section 6).

### Added

- `measurements` in `results.json`: each check that ran lists the numbers it compared with its
  rule, each with its limit, bound, unit and `ok` (docs/spec.md, section 6). A program can now read
  them without the detail text, whose wording can change. The GUI uses them for the margin of each
  joint. It is a new optional field, so `schema_version` stays 1. The verdicts and the detail text
  do not change.
- `proofmass-check run` takes several assets, and runs them in one start of the engine. Isaac Sim
  can take a minute to start, and it started once per asset before. With several assets, `--out`
  is a folder with a folder per asset. An asset that stops with an error does not stop the others.
  The exit status is the highest of the assets'. Two assets of one file name are refused.
- `proofmass-check run --events FILE`: the progress as JSON Lines, for a program that follows a
  run: the engine's start, each asset, each check with its engine operations, each verdict, the
  end (docs/gui.md, section 5.2). `runner.run_checks()` takes the callback that writes them.
- `proofmass-check inspect`: what the reader reads from an asset, and the expected plan, as JSON,
  without an engine. It gives the variant sets, the bodies, the joints with their drive and where
  it comes from (PhysicsDriveAPI or MjcActuator), the mass each joint carries and its largest
  gravity load, the applied schemas and authored attributes of each joint prim, the gripper sites,
  the wheels and the plan for one engine. `--geometry` adds the colliders. It needs pxr, so it runs
  in a Python with usd-core, not in Isaac Sim's.
- `Joint.prim`: the path of the joint's prim in the stage.
- `proofmass-check gui`: a page in the browser that shows results files, phase 1 of
  [docs/gui.md](docs/gui.md). It opens folders and finds every results file below them, whatever
  its name. It shows a matrix of runs and checks, the page of one run, a comparison of runs (PhysX
  and Newton, two versions, repeats), and a comparison of two folders paired by the asset's SHA-256.
  It saves a report as one HTML file or as CSV. It never changes an asset or a results file. The
  server listens on 127.0.0.1 only and needs the token from the address it prints. It needs
  nothing beyond the standard library. It has the look of proofmass.com: the Proofmass logo, and
  the fonts Archivo and IBM Plex Mono, which come with the package (SIL OFL 1.1, see NOTICE).
- The GUI runs checks too, phase 2 of docs/gui.md. Settings keep the Python of each engine and a
  workspace. A new batch lists the USD files of a folder, takes the engines, the Newton repeats and
  the settings, and shows the command of each run before it starts. The batch's page shows each
  asset of each run live: the check, its step and the time so far. Runs go one at a time, and a run
  can be cancelled. When a worker crashes in the middle of an asset, that asset is marked as
  stopped and a new worker runs the rest. The GUI reads the state of a batch from its files, so it
  can read it again after a restart. It never accepts the NVIDIA licence for the user.
- The GUI's inspector, phase 3 of docs/gui.md: the plan of an asset before a run, its joints,
  bodies and attributes, and a 3D view of its colliders, joints and gripper sites. Opened from a
  run, it marks the joints whose measurements failed or came close to their limits. The 3D view
  is drawn on a 2D canvas, with no library. It shows the range of the selected joint (an arc or a
  segment), the box GRIP closes on, and a wheeled robot's front (+X). The joints table filters the
  joints the checks move, push, leave without limits, or that follow another joint. inspect gives
  each joint's role (`driven`, `pushed`, `limited`), the centre of what it carries, and each gripper
  site's GRIP box.

### Changed

- `checks.wheeled.evaluate()` gives the measurements too: (ok, detail, measurements).
- The variant sets each engine reads, whether it reads MjcActuator, and the checks it supports on
  an asset are in `engines/capabilities.py`, which imports no engine. The engines take them from
  there, so the plan of `inspect` and the plan of a run cannot differ in them.

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

[Unreleased]: https://github.com/proofmass/proofmass-check/compare/v0.3.3...HEAD
[0.3.3]: https://github.com/proofmass/proofmass-check/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/proofmass/proofmass-check/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/proofmass/proofmass-check/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/proofmass/proofmass-check/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/proofmass/proofmass-check/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/proofmass/proofmass-check/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/proofmass/proofmass-check/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/proofmass/proofmass-check/releases/tag/v0.1.0
