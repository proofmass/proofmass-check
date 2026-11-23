# proofmass-check specification

Version 0.3 (draft). Version 0.3 reads the drive of a joint from an `MjcActuator` in Newton
(section 2). Version 0.2 added wheeled robots (section 4.2).

This file says what every check does and which numbers it uses. The code follows this file:
`src/proofmass_check/rules.py` holds the same numbers, and a unit test fails when the two differ.
A change to a number is a new spec version. Results of different spec versions are not compared.

A number written as `NAME` = value is the constant `NAME` in `rules.py`.

## 1. General rules

**Units.** Metres, kilograms, seconds, newtons and radians. The USD gives revolute joint angles in
degrees, and the reader converts them. Reports show angles in degrees and short distances in mm.

**Up axis.** Z up. Gravity is `GRAVITY` = 9.81 m/s² along −Z.

**Scene.** Each check starts from the asset's rest pose: each joint at its PhysicsJointStateAPI
position, else 0. The scene is an infinite floor and the asset. GRIP and SHAKE add one box.

**Floor.** `FLOOR_BELOW` = 0.001 m below the lowest collider in the file pose, and never above
z = 0. A part that only touches the floor in the file, such as a fingertip, then does not drag on
it. `--no-floor` removes the floor, for a pinned arm whose links reach below its base.

**Seed.** Every random choice uses `numpy.random.default_rng(SEED)`, with `SEED` = 0.

**Joint tolerance.** `LINEAR_TOL` = 0.002 m for a prismatic joint, `ANGULAR_TOL_DEG` = 0.5 degrees
for a revolute joint. "At a limit" means within `LIMIT_TOL` = 2 tolerances of it.

**Settle time.** `SETTLE_S` = 1.5 s. A move gets `SETTLE_S` plus the distance divided by the
joint's speed limit (`physxJoint:maxJointVelocity`), when it has one.

**Finite.** A NaN or an infinite value in a pose or a speed fails the check that measured it.

**Verdicts.** Each check gives `PASS`, `FAIL` or `N/A`, and one line of detail with the measured
numbers. `N/A` always gives the reason. A run passes when no check fails.

## 2. Reading the asset

The reader never repairs the asset. It reads the USD as an engine would:

- It selects the engine's variant set (`PhysX` for PhysX; `Newton`, else `MuJoCo`, for Newton)
  when the asset has an `Enabled` variant in it, then each `--variant` the user gives.
- A rigid body is a prim with PhysicsRigidBodyAPI. Its colliders are the prims with
  PhysicsCollisionAPI below it, down to the next rigid body: meshes, cubes and cylinders.
- A mass of 0, or no PhysicsMassAPI, means the engine computes the mass. LOAD then reads it from
  the engine.
- A joint that targets a prim inside a body means that body.
- A generic (D6) joint becomes one joint per free axis, as in PhysX. An axis whose low limit is
  above its high limit is locked.
- A mimic joint (PhysX, MuJoCo or Newton schema) follows its leader. PASSIVE does not push it.
- A joint's drive is its PhysicsDriveAPI. In Newton, a joint without one, and with one axis, gets
  its drive from an active `MjcActuator` that targets it, as Newton's importer does. The actuator
  must have the shape of MuJoCo's `<position>` or `<velocity>` shortcut: gain type `fixed`, bias
  type `affine`, no dynamics, gear 1, and with gain kp a bias of (0, -kp, -kv) for a position
  drive or (0, 0, -kp) for a velocity drive. Any other actuator is a motor that the user commands,
  and is not a drive. PhysX does not read an `MjcActuator`, so in PhysX such a joint has no drive.

Missing data is not a failure of a check. A check that needs it reports `N/A`.

## 3. Which checks run

| Check | Runs when | Else `N/A`, because |
|---|---|---|
| LOAD | always | |
| DROP | the run has a floor, the asset is not fixed to the world, is not a wheeled robot, and has no position drives | the asset is held, STAND drops it, or its joints are checked instead |
| HOLD | a joint has a position drive (stiffness > 0) | no joint has a position drive |
| TRACK, LIMIT, STABLE | a joint with a position drive has both limits | no driven joint has limits |
| SPEED | a driven joint with limits also has a speed limit | no driven joint has a speed limit |
| PASSIVE | a joint without a position drive has both limits, and follows no other joint | no such joint |
| GRIP, SHAKE | a gripper site has `gripper_maxPayload`, sits on a body, and the gripper is fixed to the world | the reason for each site |
| STAND, DRIVE | the asset is a wheeled robot and the run has a floor | not a wheeled robot |
| TURN | a wheeled robot with differential or skid-steer drive | an Ackermann robot steers instead |
| STEER | a wheeled robot with Ackermann drive | other robots turn instead |

"Fixed to the world" means a fixed joint with one side empty. A wheeled robot is an asset whose
root layer has `SimReady_Metadata.mobile` ([wheeled-robots.md](wheeled-robots.md)). When LOAD
finds that the engine did not build every joint, every other check reports `N/A`.

**Wheeled robots.** LOAD, the drive checks and PASSIVE run with the robot's root body held
`BASE_LIFT` = 0.05 m above its file pose, so the wheels do not touch the floor. A joint with a
damping-only drive is a wheel there, so PASSIVE does not push it.

## 4. The checks

### 4.1 All assets

### LOAD: the engine builds the asset as the USD describes it

- **Why:** an engine can drop a joint without an error, or compute masses the USD does not give.
- **Rule:** every joint the engine builds is in the USD, every moving joint of the USD is built,
  and the engine's total mass is within `MASS_TOL` = 0.01 of the USD's (only when the USD gives
  every mass).
- **Report:** joint count by drive kind, both masses, and the joints that do not match.

### DROP: dropped, it comes to rest on the floor

- **Why:** the most common failure of an asset: missing or wrong colliders, a bad mass or
  inertia, or parts that overlap and push each other apart.
- **Setup:** every body is lifted by `DROP_HEIGHT` = 0.1 m. The asset falls for
  `DROP_SECONDS` = 3.0 s.
- **Rule:** all values finite, the root body slower than `REST_SPEED` = 0.05 m/s, and the lowest
  collider within `FLOOR_TOL` = 0.002 m of the floor, above or below.
- **Report:** speed, distance to the floor in mm, and the tilt from the file pose. The tilt does
  not decide the result: a prop may come to rest on its side.

### HOLD: drives hold the rest pose under gravity

- **Setup:** every position-driven joint is driven to its rest position for `SETTLE_S`.
- **Rule:** every one ends within one tolerance of its rest position.

### TRACK: drives reach targets inside their range

- **Setup:** each driven joint with limits, one at a time, is driven to `TRACK_AT` = (0.25, 0.75)
  of its range. The other driven joints hold their rest positions.
- **Rule:** each target is reached within one tolerance.

### LIMIT: limits stop a drive commanded past them

- **Setup:** each driven joint with limits, one at a time, is driven to its upper limit plus
  `OVERSHOOT` = 0.2 of its range.
- **Rule:** the joint goes past its upper limit by at most `LIMIT_TOL` tolerances.

### STABLE: no explosion in random poses

- **Setup:** `RANDOM_POSES` = 50 poses. In each, every driven joint with limits gets a uniform
  random target inside its limits, and the pose is held for `SETTLE_S`.
- **Rule:** in every pose, all values finite and no joint faster than `UNSTABLE_SPEED` = 50 rad/s
  or m/s.

### SPEED: drives stay under their speed limits

- **Why:** an asset that is stable at a small physics step can break at the step most users run.
  This follows NVIDIA's `velocity_limit` benchmark.
- **Setup:** the physics step is `SPEED_DT` = 1/60 s, Isaac Sim's default. Each driven joint with
  limits and a speed limit, one at a time, moves for `SPEED_SECONDS` = 2.0 s to the end of its
  range farther from rest, `SPEED_MARGIN` = 0.05 of the range short of it.
- **Rule:** after the first `SPEED_SKIP_STEPS` = 5 steps, the joint's speed stays within its
  speed limit plus `SPEED_TOL` = 0.05 of it. At the end, every driven joint is inside its limits,
  give or take `LIMIT_TOL` tolerances.
- **Report:** the highest speed after the first steps. A short joint, such as a gripper finger,
  can end its move inside the first steps, and the check then measures a joint that already
  stands. When the joint was faster in the first steps, the result gives that speed too. It does
  not change the verdict.

### PASSIVE: a door or drawer opens to its limits and stops there

- **Setup:** each joint is pushed from rest for `PUSH_SETTLE` = 2 times `SETTLE_S`, first toward
  its upper limit, then toward its lower limit.
  - The base push is `PUSH_GRAVITY_FACTOR` = 1.5 times the gravity load the joint carries, plus
    enough to accelerate it at `PUSH_ACCEL_LINEAR` = 2.0 m/s² or `PUSH_ACCEL_ANGULAR` = 4.0
    rad/s², plus what a damping-only drive (a door closer) needs to cross the range in half the
    push time. For a revolute joint, the lever is at least `PUSH_MIN_LEVER` = 0.05 m.
  - A push that does not reach the limit is tried again `PUSH_STEP` = 4.0 times stronger, up to
    the base push plus `HAND_FORCE` = 50.0 N at the handle. On a revolute joint the handle is twice
    as far from the axis as the centre of mass.
- **Rule:** at each limit, the joint ends within `LIMIT_TOL` tolerances of it.
- **Report:** the distance from each limit, and the push it needed.

### GRIP: the gripper holds its rated payload

- **Why:** this follows NVIDIA's FET028 gripper test.
- **Setup:**
  - A box at the grasp centre: `GRIP_WIDTH` = 0.7 of `gripper_maxOpening` across the pads, and the
    pad size (the length of `gripper_grip_line`, else `PAD_WIDTH` = 0.02 m) in the other two
    directions. Friction `GRIP_FRICTION` = 2.0, static and dynamic. The box has no weight.
  - The finger drives close to their closing limits. A finger joint is a limited, position-driven
    joint below the site's body that moves its bodies at least `GRIP_MIN_TRAVEL` = 0.001 m toward
    the grasp centre. The other drives hold their rest positions.
  - The box is pulled with its mass times g for `GRIP_HOLD_S` = 2.0 s, first out of the fingers,
    then along the grip line. The loads rise through `GRIP_LOADS` = (0.25, 0.5, 0.85, 1.0, 1.5, 2.0)
    times `gripper_maxPayload`, up to the first slip.
- **Rule:** in both directions, the highest load held is at least `GRIP_LOAD` = 0.85 times
  `gripper_maxPayload`. Held means: at least one finger stopped on the box, short of its closing
  limit by more than `LIMIT_TOL` tolerances, and the box slid less than `GRIP_SLIP` = 0.005 m along
  the pads. Motion along the closing axis is drift, not a slip.

### SHAKE: the grip holds while shaken

- **Setup:** as GRIP, with `GRIP_LOAD` times `gripper_maxPayload`, pulled out of the fingers with
  load × g × (1 + sin(2π f t)), with f = `SHAKE_HZ` = 2.0 Hz. So the pull reaches 2 g.
- **Rule:** as GRIP.

### 4.2 Wheeled robots

The robot's front faces +X, left is +Y and up is +Z (ROS REP-103). Every check follows one point:
the centre of the driven axle, which the robot turns about. Its pose is recorded every
`BASE_SAMPLE_DT` = 0.02 s. The robot drives at `WHEEL_SPEED` = 0.5 m/s, or at
`WHEEL_LIMIT_FRACTION` = 0.5 of the slowest driven wheel's speed limit when that is lower.
Speeds and rates are measured after a start-up of `STARTUP_S` = 1.5 s, or of
`STARTUP_FRACTION` = 0.4 of the run when that is shorter.

#### STAND: it stands upright and still

- **Setup:** dropped from `DROP_HEIGHT` with every driven wheel braked (speed 0), for
  `STAND_SECONDS` = 3.0 s.
- **Rule:** at the end it leans less than `STAND_TILT_DEG` = 2.0 degrees and moves slower than
  `STAND_SPEED` = 0.02 m/s.

#### DRIVE: it drives straight at the commanded speed

- **Setup:** every driven wheel forward at the test speed, for `DRIVE_SECONDS` = 4.0 s.
- **Rule:** it moves toward +X; its speed is within `DRIVE_SPEED_TOL` = 0.1 of the command; it
  drifts sideways less than `DRIVE_DRIFT_TOL` = 0.03 of the distance; its heading changes less than
  `DRIVE_YAW_TOL_DEG` = 3.0 degrees.

#### TURN: it turns in place (differential and skid-steer drive)

- **Setup:** left wheels backward and right wheels forward at the test speed, for
  `TURN_SECONDS` = 4.0 s. The expected yaw rate is 2 × speed / track.
- **Rule (differential):** the yaw rate is within `TURN_TOL` = 0.15 of the expected rate, and the
  axle centre moves less than `TURN_DRIFT` = 0.05 m.
- **Rule (skid steer):** a skid-steer robot turns by sliding its wheels, so its rate depends on the
  engine's friction model. It must turn left faster than `SKID_TURN_MIN` = 0.1 of the expected rate,
  and its axle centre must stay within one track width.

#### STEER: it drives the circle its steering gives (Ackermann drive)

- **Setup:** the inner front wheel turns `STEER_FRACTION` = 0.5 of its steering range to the left,
  the outer one to the Ackermann angle for the same centre. Each driven wheel gets the speed of its
  own circle. It drives a quarter circle plus 1 s, at most `STEER_MAX_SECONDS` = 8.0 s.
- **Rule:** it turns left, and the radius of the circle fitted to its path is within `TURN_TOL`
  of the Ackermann radius.

## 5. Engines

Every engine runs the same plan and the same rules. An engine that cannot run a check yet reports
`N/A` for it. When the asset needs that check, the run also names it in `engine_cannot_run` and in a
note: a PASS does not cover it, and a report must say so next to the verdict, not only in the notes.

| Engine | Status | Physics step | Not run yet |
|---|---|---|---|
| PhysX (Isaac Sim 6.1) | reference | 1/240 s; SPEED uses its own step | HOLD, TRACK, LIMIT, STABLE, SPEED, GRIP and SHAKE on an asset without PhysicsArticulationRootAPI |
| Newton | experimental | 0.002 s, MuJoCo Warp solver | SPEED; STAND, DRIVE, TURN, STEER; the axes of a D6 joint, which the run's notes list |

Two things about Newton that a reader of its results must know:

- **Results can differ from run to run.** On the GPU, the same asset can give slightly different
  numbers each run. A joint close to a rule's limit can pass in one run and fail in the next.
  PhysX gave the same numbers in every run we compared.
- **Joint limits are soft.** When the USD does not set them, Newton's limits are stiff springs with
  little damping. A joint without damping or friction can bounce between its limits and not come
  to rest at one, so PASSIVE fails. In PhysX the same joint stops at the limit.
- **PhysX joint friction is not read.** `physxJoint:jointFriction` is a PhysX attribute. Newton
  moves the joint without it, so a joint that friction holds still in PhysX can pass PASSIVE in
  Newton. A note names each joint that has it, with its value, in every engine but PhysX.

## 6. Results

`results.json` follows `src/proofmass_check/results.schema.json`. It records the spec version,
the tool and engine versions, the SHA-256 of the asset's root file, the variants, the settings,
every verdict with its detail, and notes. `engine_cannot_run` lists the checks the asset needs that
the engine cannot run yet (section 5). Results of tool 0.3.0 and older do not have it.

**Measurements.** Each check that ran also lists the numbers it compared with its rule, so that a
program can read them without the detail text. A measurement has a subject (a joint, a gripper
site, or empty for the whole asset), a case, a quantity, a value and a limit in SI units, a bound
(`max`: the rule wants value <= limit, `min`: value >= limit), a unit, and `ok`.

- `ok` is what the check decided for that number, with the comparison that decides its verdict. A
  check passes when every one of its measurements is ok. GRIP, when no drive closes the fingers,
  and a wheeled check whose path is not finite fail with no measurements.
- A value that is not finite is written as `null`. The limit is `null` for a number the check
  reports but does not judge.
- The detail text says the same in words. Only the measurements are meant for programs: the text
  can change between versions.

| Check | Subject and case | Quantity: limit |
|---|---|---|
| LOAD | asset | joints the engine did not build: 0; engine joints not in the USD: 0; mass difference (a fraction of the USD mass): `MASS_TOL`, only when the USD gives every mass |
| DROP | asset | final speed: `REST_SPEED`; lowest collider from the floor (signed): `FLOOR_TOL`; tilt: none |
| HOLD | joint | error: one tolerance |
| TRACK | joint, `25%` and `75%` | error: one tolerance |
| LIMIT | joint, `upper` | past the limit: `LIMIT_TOL` tolerances |
| STABLE | asset | unstable poses: 0 |
| SPEED | joint | highest speed: the speed limit plus `SPEED_TOL`; driven joints outside their limits at the end: 0; speed in the steps not measured: none |
| PASSIVE | joint, `upper` and `lower` | distance from the limit: `LIMIT_TOL` tolerances; push: the hand push |
| GRIP | site, `out of the fingers` and `along the grip line` | highest load held (kg, `min`): `GRIP_LOAD` times `gripper_maxPayload` |
| SHAKE | site | slip along the pads: `GRIP_SLIP` |
| STAND | asset | tilt: `STAND_TILT_DEG`; speed: `STAND_SPEED` |
| DRIVE | asset | distance along +X (`min`): 0, and the sideways drift no larger; speed error: `DRIVE_SPEED_TOL` of the command; sideways drift: `DRIVE_DRIFT_TOL` of the distance; heading change: `DRIVE_YAW_TOL_DEG` |
| TURN | asset | differential: yaw rate error, `TURN_TOL` of the expected rate, and centre drift, `TURN_DRIFT`. Skid steer: yaw rate (`min`), `SKID_TURN_MIN` of the expected rate, and centre drift, one track width |
| STEER | asset | turning radius error: `TURN_TOL` of the Ackermann radius; yaw rate (`min`): 0 |

## 7. Not in this version

- Wheeled robots without `SimReady_Metadata.mobile`: the checks do not find their wheels yet.
- Visual and material checks. NVIDIA's validator covers them.
- Speed of the simulation.
