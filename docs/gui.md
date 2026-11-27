# proofmass-check GUI: design

Version 0.5 (draft). Phases 1 to 3, the viewer, the runner and the inspector, are built in 0.3.0
(section 8). The replay (phase 4) and experiments are not. This file says what the GUI does, how
it is built, and what must change in proofmass-check before it. [spec.md](spec.md) stays the
authority for the checks: the GUI shows what the checks decide, and never decides itself.

## 1. Goal

proofmass-check tests one asset in one engine, from the command line, and writes `results.json`.
The GUI makes three tasks fast that are slow today:

1. Run many assets in both engines, and see which fail and where.
2. Find the joint that fails, and how far it is from its rule.
3. Compare runs: PhysX with Newton, one tool version with the next, or repeated Newton runs.

These tasks come from the audits of Lightwheel's appliances (10 assets) and AgiBot's G2 (46
joints) in November 2026. In both, the results were read from `results.json` by hand, and scripts
outside this repository listed the joints, drives and friction and made the report.

A fourth task came after them:

4. See what a check did to the asset: how a joint moved, where the box slipped, which pose blew
   up. In the run of Isaac Sim's robots for spec 0.4, a UR5e failed TRACK by 178.6 deg: its
   wrist starts 19 mm above the floor, and the arm touched the floor 1.6 deg into the move of its
   shoulder. The results say only how far the joint is from its target. A replay of the move
   shows the cause (sections 5.5 and 6.11).

**What the GUI never does:**

- It never changes an asset, and never changes a setting to make a check pass.
- It never decides a verdict. `checks/` decides, and the GUI shows `results.json`.
- It never accepts the NVIDIA Omniverse License Agreement for the user, and never sets
  `OMNI_KIT_ACCEPT_EULA`.
- It never sends data off the computer: no CDN, no telemetry. An asset's licence can forbid
  uploading it (Lightwheel's set is CC BY-NC 4.0).

## 2. Words

| Word | Meaning |
|---|---|
| run | one asset in one engine. It gives one `results.json`, as `runner.Run` does. |
| batch | the runs the GUI starts together: some assets, in one or two engines, with one set of settings |
| workspace | the folder where the GUI keeps its batches |
| worker | a process that runs proofmass-check in an engine's Python |
| measurement | one number that a check compared with its rule, with the rule's limit (section 5.1) |
| margin | how much of its limit a measurement uses: value / limit, or limit / value for a lower bound. Above 1, the measurement fails its rule. |
| replay | the motion of every body during a run, recorded with `run --replay` in one file next to `results.json` (section 5.5) |
| clip | the part of a replay that one engine operation gives: one settle, move, push, drop, drive or grip trial |
| frame | the pose of every body at one time of a clip |

## 3. Users

Two kinds of user. Which one comes first is open (section 11).

| User | Works on | Needs most |
|---|---|---|
| Auditor | batches of assets from other makers, in both engines, and a report at the end | batch view, compare, report |
| Asset maker | one asset, in a loop: change the USD, run, see what changed | a fast run of one asset, the joint view, the difference from the last run |

Both need the joint view with margins, and the reason for each `N/A`.

## 4. How it is built

```
browser --HTTP, 127.0.0.1--> proofmass-check gui            any Python 3.11+ with proofmass-check
                                 |  reads and writes the workspace
                                 |-- worker: <Isaac Sim's Python> -m proofmass_check run ...      PhysX
                                 |-- worker: <Newton's Python>    -m proofmass_check run ...      Newton
                                 '-- worker: <a Python with pxr>  -m proofmass_check inspect ...  no engine
```

- `proofmass-check gui [FOLDER ...] [--workspace DIR]` starts a local HTTP server and opens the
  browser. The folders open as results folders. `--workspace` gives the workspace for this session
  only, in place of the one in the settings.
- The server uses the standard library only: `http.server`, `subprocess`, `json`. The package keeps
  numpy as its only dependency.
- The front end is static HTML, CSS and JavaScript in `src/proofmass_check/gui/static/`, with no
  build step and no library of others. The 3D view (`viewer3d.js`) draws the colliders' triangles
  from far to near on a 2D canvas, which is enough for convex hulls of a few dozen faces.
- Engines run only in workers. The server never imports pxr, isaacsim or newton, because each
  engine needs its own Python (README, "Engines"), and in Isaac Sim pxr exists only after Isaac
  Sim has started.
- A worker gives its results to the server only through files: `results.json`, `events.jsonl`, its
  log, and the replay when the batch records one. So the command line stays the one interface,
  and a run from the GUI writes the same `results.json` as the same command in a terminal.

### 4.1 Pythons

The settings file holds one Python per engine: `%APPDATA%\proofmass-check\gui.json` on Windows,
`~/.config/proofmass-check/gui.json` on Linux.

- The GUI tests each Python with `<python> -m proofmass_check --version` and shows the tool and
  spec versions it prints, or the error.
- When a worker's version differs from the GUI's, the GUI says so before a batch starts.
  `batch.json` records the version of every worker.
- `inspect` needs pxr without Isaac Sim: the GUI's own Python with the `usd` extra, or Newton's.
  It must not be Isaac Sim's Python. There, pxr exists only after Isaac Sim starts, and a second
  pxr from usd-core can clash with Isaac Sim's own (pyproject.toml).

### 4.2 Security

The server starts processes, so a web page open in the same browser must not reach it.

- It listens on 127.0.0.1 only.
- The command opens the browser with a random token in the URL. Every API request must carry it.
- It checks the Host header, which stops DNS rebinding. It checks the Origin header and sends no
  CORS headers, so another page cannot send it requests.
- A worker runs only a Python from the settings file, with an argument list and never through a
  shell. A path in a request is a file to read, never a command.
- It serves files only from the static folder, the workspace, and the folders the user opened in
  this session.

### 4.3 The workspace

```
<workspace>/
  2026-11-22_140512_lightwheel/           a batch: date, time, name
    batch.json                            assets, engines, settings, each run's Python and its version
    physx/events-1.jsonl                  the progress of the run's first worker (section 5.2)
    physx/log-1.txt                       that worker's stdout and stderr
    physx/Dishwasher036/results.json      as the command line writes it
    physx/Dishwasher036/replay.bin        the motion of each check, when the batch records it (5.5)
    newton/..., newton-2/...              a run for each engine, and for each repeat in Newton
```

- A run is one engine, or one repeat in Newton. A worker is one process of `run` with the assets
  the run still needs. A second worker of a run, after a crash, writes `events-2.jsonl` and
  `log-2.txt`.
- An asset's folder has the name of its root file without the extension. So two assets of one
  name cannot be in one batch: the GUI and `run` both say so.
- The GUI reads the state of a batch only from these files, so it can read it again after a
  restart. Only whether a worker runs now is kept in memory.
- A batch folder does not change after the batch ends. To run again, start a new batch.
- The GUI also opens any folder that holds results files, read-only, for example results made
  before the GUI existed. A results file is any JSON file whose `tool.name` is `proofmass-check`,
  whatever the file is called, because people rename them (`physx_results.json`). Folders whose
  names start with "." are not read.

## 5. Changes to proofmass-check first

Each change is useful on the command line without the GUI. Each one gets its own pull request and
its own line in CHANGELOG.md.

### 5.1 Measurements in results.json

Built in version 0.3.0. spec.md section 6 gives the measurements of each check, and is the
authority for them. This section says why they exist.

Before, each check gave one `detail` line only. The GUI needs the numbers, to sort joints by margin
and to compare runs. The detail line is text for people, and its wording changes between versions
(0.1.2 changed the text of SPEED). So the GUI never parses it.

Each check result has an optional `measurements` array. `detail` stays as it is.

```json
{
  "id": "PASSIVE",
  "verdict": "FAIL",
  "detail": "door_joint@upper 27.670 deg from the limit at the hand push 74 N m FAIL; ...",
  "measurements": [
    {"subject": "door_joint", "case": "upper", "quantity": "distance from the limit",
     "value": 0.48293, "limit": 0.017453, "bound": "max", "unit": "rad", "ok": false}
  ]
}
```

| Field | Meaning |
|---|---|
| `subject` | a joint name, a gripper site name, or empty for a number of the whole asset. The asset's name is often only `root`, so it would say nothing. |
| `case` | which test of the subject: `25%`, `upper`, `out of the fingers`, and so on. Empty when the subject has one. |
| `quantity` | what was measured, from a fixed list for each check (spec.md section 6) |
| `value` | in SI units, as the rest of the file. `null` when the engine gave a value that is not finite. |
| `limit` | the rule's limit, in the same unit. `null` when the rule sets none (a tilt that DROP reports only). |
| `bound` | `max`: the rule wants value <= limit. `min`: value >= limit. |
| `unit` | `m`, `rad`, `m/s`, `rad/s`, `kg`, `N`, `N m`, or `1` for a count or a fraction |
| `ok` | what the check decided for this measurement |

- `ok` comes from the check. A check can need more than one value to decide (all values finite,
  for example), so the GUI shows `ok` and never compares `value` and `limit` itself.
- Values are not rounded.
- It is a new optional field, so `schema_version` stays 1 (report.py). `results.schema.json`
  describes it.
- A check passes when all its measurements are ok, and a test holds every check to that.

### 5.2 Progress events

Built in phase 2. In the Lightwheel batch, one run took 10 s to 54 s, without the start of Isaac
Sim, and the command prints its results only at the end. The option `--events FILE` writes JSON
Lines as the run goes: one object per line, flushed after each line (`events.py`).

Every event has `event` and `t`, the seconds since the command started. The events of one asset
also have `asset`, its file as the command line gave it.

| Event | Fields |
|---|---|
| `start` | the asset files, the engine, the tool and spec versions |
| `engine` | the engine's versions, and the seconds it took to start |
| `error` | why the engine did not start. `exit` follows. |
| `asset` | an asset starts |
| `check` | a check starts: its ID, and `total`, the engine operations it makes, when the plan knows it |
| `plan` | after LOAD: the checks that will run (`runs`), and each other one with its reason (`skip`) |
| `step` | the check ID, the engine operations done, and `total` |
| `result` | a check's ID and verdict |
| `end` | an asset ends: passed, failed, seconds and the path of `results.json`, or the error |
| `exit` | the command's exit status, just before the engine closes |

- `step` comes from a wrapper around the engine that counts its operations (settle, move, push).
  The checks do not change. When the plan cannot know the count, `step` has no total: PASSIVE, for
  example, pushes again when a push does not reach the limit.
- The events go to a file, not to stdout. stdout stays for people, and the GUI does not depend on
  what an engine prints.

### 5.3 The inspect command

```bash
proofmass-check inspect path/to/asset.usd --engine physx --variant SET=VALUE --geometry
```

Built in phase 3 (`inspection.py`). It prints, as JSON, what the reader read and the plan,
without starting an engine. `--out FILE` writes the JSON to a file.

- **What it gives:** the variant sets with their values and the ones selected; bodies (path, mass
  or none, centre of mass, pose, and with `--geometry` the colliders); joints (every field of
  `model.Joint`, in SI units); gripper sites; the wheeled base; the floor height; the plan (each
  check runs, or is `N/A` with the reason); and the notes.
- **Authored attributes:** for each joint prim, its applied schemas and authored attributes, as
  text. This shows values the reader does not use, such as `physxJoint:jointFriction`, or a drive
  instance that PhysX does not read (`PhysicsDriveAPI:X`). Both caused failures in the Lightwheel
  set.
- **The plan without an engine:** the plan needs the engine's `supported` set, and
  `engines/physx.py` imports isaacsim at the top. So what depends only on the asset is in
  `engines/capabilities.py`, which imports no engine, and the engines take it from there: PhysX
  runs only LOAD, DROP and PASSIVE on an asset without PhysicsArticulationRootAPI, and Newton does
  not run SPEED, STAND, DRIVE, TURN and STEER. The variant sets each engine reads, and whether it
  reads MjcActuator, are there too.
- **In the GUI:** the server runs inspect as a process of its own, never in its own process: in
  the GUI's Python when it has pxr, else in Newton's Python. It keeps the last 8 inspections.
- **What only the engine knows:** two things are known only after the engine builds the asset.
  In Newton, DROP needs a free joint. And an engine can have joints it cannot drive or measure one
  by one (`LoadOutcome.not_addressable`). So inspect calls its plan "expected", and the GUI shows
  that word.

### 5.4 Several assets in one run

Built in phase 2. Each run started the engine and closed it, and PhysX ends the process when it
closes. Isaac Sim can take a minute to start the first time (`engines/__init__.py`). So a batch of
10 assets started Isaac Sim 10 times.

`run` takes several assets: `proofmass-check run a.usd b.usd --out DIR` writes
`DIR/<asset>/results.json`. With one asset, `--out DIR` still writes `DIR/results.json`. The engine
starts once. `Engine.open()` loads each asset into the same engine.

- A run must not depend on the asset before it. A GPU test runs an asset, another one, and the
  first again, and compares the results (in Newton, the verdicts only).
- An asset that stops with an error gets `results.json` with the error, and the next asset runs.
- The exit status is the highest status of its runs.
- Two assets of one file name are refused: their folders would be the same.
- When a worker stops in the middle of an asset, as an engine that crashes does, the GUI marks
  that asset as stopped and starts a new worker with the assets that are left.

### 5.5 The replay

Not built (phase 4). `results.json` holds the numbers that a check compared with its rule, but
not the motion that gave them. The engines compute the pose of every body at every step, and
nothing keeps it. The option `--replay` writes that motion to `replay.bin`, next to `results.json`:

```bash
proofmass-check run path/to/asset.usd --engine physx --replay
```

With several assets, each asset's folder gets its own `replay.bin`, as it gets its own
`results.json` (section 5.4).

**What is recorded:**

- Each engine operation gives one clip: a settle, a move, a push, a drop, a drive, or one trial of
  the grip scene. LOAD gives none, because it only builds the asset.
- A frame holds its time from the start of the clip, then the position and rotation of each body
  of `asset.bodies`, in the world. A clip of the grip scene also holds the grip box, after the
  bodies.
- The first frame is the state at the start of the operation: after the reset, and after the
  lift of DROP or of a wheeled check. Then a frame comes each 1/30 s of simulated time, to the
  nearest step: every 8th step of PhysX's 1/240 s, and every 2nd step of SPEED's 1/60 s. Newton
  records at the end of each CUDA graph. When it records, a graph has 16 steps of 0.002 s, so
  Newton gives 31 frames per second. The last frame is always the state at the end of the
  operation, which the check measured.
- The file holds body poses, not joint positions. A joint that comes apart, or a body that flies
  off in STABLE, shows as it happened. Joint positions would hide both.
- A value that is not finite stays NaN in the file.

**Each clip has a label**, so the GUI can play the clip of a measurement (section 6.11):

| Field | Meaning |
|---|---|
| `check` | the check ID. The shaken trial of the grip scene has `SHAKE`. |
| `subject`, `case` | those of the measurement the clip gives (section 5.1). Empty for a clip of the whole asset: HOLD, DROP, STABLE and the wheeled checks. |
| `attempt` | which clip of several for one measurement: `pose 17` in STABLE, `push 74 N m` in PASSIVE, `1.7 kg` in GRIP. Empty when there is one. |
| `ok` | what the check decided from this clip: the joint reached its target, the pose was stable, the box held |
| `operation` | `settle`, `move`, `push`, `drop`, `drive` or `trial` |
| `arguments` | the operation's arguments: the targets, the pushed joint and its effort, the load and its direction |

- The runner gives the check ID, as it does for the `step` events (section 5.2). The grip check
  gives `SHAKE` for its shaken trial. The check gives the rest: it wraps each engine call in
  `replay.label(subject, case, attempt)`, and sets the label's `ok` when it has decided. Without
  `--replay`, the label does nothing. A check decides nothing differently because of it.
- The engine gets a recorder from the runner, or none when the run does not record. Each engine
  calls it from the one place where it steps: PhysX gets one step method that every loop calls,
  and Newton records in `_Sim.run` and in the shaken pull. The runner's wrapper that counts
  operations for the `step` events also starts and ends a clip around each operation.

**The file** is binary, because a JSON file of the same frames would be several times larger and
slow to read. Also, the GUI reads every JSON file in an opened folder to find results files
(section 4.3), so a large JSON file there would slow every scan.

```
replay.bin
  8 bytes   "PMREPLAY"
  4 bytes   the format version, 1, as a little-endian uint32
  4 bytes   n, the length of the header in bytes, as a little-endian uint32
  n bytes   the header: JSON in UTF-8, padded with spaces to a multiple of 4 bytes
  the rest  the frames, as little-endian float32
```

```json
{
  "id": "4f1c09d2a7e85b3c6d10e2f4a9b87c55",
  "engine": "physx",
  "sha256": "<the SHA-256 of the root file, as in results.json>",
  "bodies": ["/ur5e/base_link", "/ur5e/shoulder_link", "..."],
  "clips": [
    {"check": "TRACK", "subject": "shoulder_lift_joint", "case": "25%", "attempt": "", "ok": false,
     "operation": "settle",
     "arguments": {"targets": {"shoulder_lift_joint": -3.1416, "...": 0.0}, "seconds": 1.5},
     "box": null, "offset": 0, "frames": 46}
  ]
}
```

- A frame is `t`, then `x y z qw qx qy qz` for each body, and for the box when the clip has one.
  The quaternion is in the order of `geometry.quat_to_matrix`.
- `offset` counts float32 values from the start of the frames, and `frames` is the number of
  frames in the clip. `box` is the size of the grip box in m, along its three axes, or null.
- `results.json` gets an optional field `replay`: `{"file": "replay.bin", "id": "..."}`. The id
  is random and new for each run. The GUI plays a replay only when its id is the one in
  `results.json`. So a replay that an older run left in the folder is never shown as the
  replay of a newer run. It is a new optional field, so `schema_version` stays 1, and
  `results.schema.json` describes it.
- The header holds no file path, as a report holds none by default (section 6.8).
- The file has no `.json` name, so the scan of a folder never reads it.

To read it without the GUI:

```python
import json
import numpy as np

data = open("replay.bin", "rb").read()
n = int.from_bytes(data[12:16], "little")
header = json.loads(data[16 : 16 + n])
values = np.frombuffer(data, "<f4", offset=16 + n)
clip = header["clips"][0]
width = 1 + 7 * (len(header["bodies"]) + (clip["box"] is not None))
frames = values[clip["offset"] : clip["offset"] + clip["frames"] * width].reshape(clip["frames"], width)
```

**Size.** A frame takes 4 × (1 + 7 × bodies) bytes, and there are about 30 frames in each second of
simulated time. Estimates from the rule numbers in spec.md, not measured:

| Asset | Bodies | Simulated time | Size |
|---|---|---|---|
| an appliance with two doors: DROP and PASSIVE | 3 | up to 40 s | under 200 kB |
| an arm of 6 joints, such as a UR5e | 7 | about 130 s | under 1 MB |
| AgiBot's G2, 46 joints | about 50 | about 420 s | about 18 MB |

**Cost.** Each frame reads the pose of every body from the engine. In Newton, it also waits for
the GPU, and the CUDA graphs are shorter. This cost is not measured yet. Phase 4 measures it on
the G2 in both engines (section 11).

**The same results.** Recording reads the state and never writes it. So `results.json` must be
the same with and without `--replay`, apart from `seconds` and `replay`. In Newton, graphs of 16
steps run the same steps in the same order as graphs of 50. The tests in section 9 check this.

**When a run stops:**

- An asset that stops with an error gets the clips recorded before the error.
- The frames stay in memory until the asset ends. So a worker that crashes in the middle of an
  asset writes no replay for it.

## 6. Screens

The phase of each screen is in brackets (section 8).

### 6.1 Batches (phases 1 and 2)

The batches in the workspace, the newest first: name, date, engines, number of assets, passed,
failed and error. Below them, the folders the user opened.

Actions: open a batch, start a new batch, open a folder. Compare two folders and save a report from
the matrix of a folder.

### 6.2 New batch (phase 2, built)

- **Assets:** a file or a folder. The GUI lists the USD files it finds, and the user ticks the root
  files. It does not guess which file is the root.
- **Engines:** PhysX, Newton, or both. Each shows its Python and versions, or why it cannot run.
- **Newton repeats:** 1 or more runs of each asset (section 6.7).
- **Variants:** the variant sets the assets have (from inspect, phase 3). Before phase 3, typed as
  `SET=VALUE`.
- **Settings:** settle time and floor. Each shows the spec's value next to it. A value that is not
  the spec's gets a mark here and on every screen of its results, because `results.json` then
  says that the settings differ from the spec.
- **Replay (phase 4):** record the motion of each check (`--replay`, section 5.5). Whether it is
  ticked by default is open (section 11). `batch.json` records the choice.
- **The command:** the command line each worker will run, to copy, so a run from the GUI can be
  repeated without it.
- **Start:** the GUI tests each engine's Python again, writes `batch.json`, and queues the runs.
  One worker runs at a time, in the order of the runs, because each engine needs the GPU.

### 6.3 Batch view (phase 1; live in phase 2, built)

- **Matrix:** one row per asset and engine, one column per check. The four wheeled checks share one
  column that opens into four. A cell shows PASS, FAIL, `N/A`, error, running or waiting, as a
  colour and a sign, never as a colour only.
- **Each row:** the run's verdict, its seconds, and its highest margin. A run with
  `engine_cannot_run` carries "N not run" next to its verdict, and a banner above the matrix says
  that a pass does not cover those checks (spec.md, section 5). A run with `wheels_without_mobile`
  carries "wheels not checked", with the joints in its tooltip, and a banner says why. A run with
  `gripper_without_site` carries "grip not checked" in the same way.
- **Filters:** only failed runs, one check, text in the asset name.
- **A cell:** shows the check's detail line on hover. A click on a row opens the asset view.
- **Live (phase 2):** above the matrix, a table of the batch's assets and runs. A running asset
  shows its check, the step of that check from the events, and the time so far. An ended asset
  links to its page. Cancel one run, or the batch: the asset a worker is on gets no
  `results.json`. The log of each run's newest worker, and the command of each run, open below.
  When an asset ends, the matrix is read again.
- **When the GUI closes:** it stops the worker that runs, so no engine runs on without it.
- **Header:** counts by verdict, for the batch and for each check; total time; versions; a banner
  when the settings are not the spec's.

### 6.4 Asset view (phase 1)

**Header:** asset name, file, SHA-256 (short, full on copy), variants, engine and its versions, tool
and spec versions, seconds, verdict. The notes from `results.json` follow the header and are never
folded away.

**Joints**, when the results have measurements:

- One row for each measurement, grouped by subject: the joint, the site, or the whole asset.
- Sorted with failed measurements first, then by margin, highest first.
- Columns: subject, check, case, value (deg or mm for a joint), limit, a margin bar, `ok`.
- A margin above the "close" level gets a mark: it passes, but a small change in the asset or the
  engine can make it fail. The level is 0.8 by default. It is a GUI setting, not a rule of the spec,
  and it never changes a verdict. In Newton it matters most, because its results can differ from
  run to run (spec.md section 5).
- When the run has a replay (phase 4), each row has a play button. It opens the inspector and
  plays the clips of that measurement (section 6.11). A row of LOAD has none: LOAD gives no clip.

**Checks:** each check with its title, verdict, detail line as written (one part per line, and a
part that ends with FAIL marked), measurements, and a link to
its section of spec.md at the run's tool version:
`https://github.com/proofmass/proofmass-check/blob/v<tool version>/docs/spec.md`. The `N/A` checks
come last, each with its reason.

**Results without measurements** (tool 0.2.0 and older): the screen shows the detail lines and says
why there is no joints table.

**Actions:** 3D view and inspector (phase 3), the replay of each check (phase 4), compare, copy the
command line, open the folder.

### 6.5 Inspector (phase 3, built)

From `inspect`, so it works before a run and without an engine. It opens from the page of a run
("Inspect the asset", with the run's engine, variants and floor) and from each file of a new batch.
A switch shows the plan for PhysX or for Newton.

- **Joints:** name, type, bodies, limits (deg or mm), rest position, drive (stiffness, damping, max
  force) and where it comes from (PhysicsDriveAPI or MjcActuator), speed limit, mimic leader and
  ratio, the D6 joint it came from. Filters show the joints the drive checks move, the ones PASSIVE
  pushes, the ones with no limits, the ones that follow another joint, and the ones a run marked.
  inspect gives each joint's role from the same sets as the plan (`driven`, `pushed`, `limited`).
- **Load on a joint:** the mass it carries (the bodies `Asset.carried` gives) and the distance of
  that mass's centre from the joint axis, and the largest gravity load, next to the drive's max
  force. The gravity load is the term PASSIVE starts its push from. With these, a user can see a
  fault like the G2's waist: 50 N m drives under 57 kg. The GUI shows the numbers and gives no
  verdict on them.
- **Bodies:** mass as given, or "the engine computes it"; number of colliders.
- **Authored attributes** of each joint prim (section 5.3).
- **Plan:** each check runs, or is `N/A` with its reason, marked "expected".

### 6.6 3D view (phase 3, built)

- **Colliders** from `inspect --geometry`: hulls, cylinders and spheres in the file pose. Past 100 000
  hull triangles (a collider that is a full render mesh), the view leaves the hulls out and says so. No render meshes:
  the view shows what the engine collides, which is what the checks test.
- **Joints:** pivot and axis. The selected joint shows its range where the body it moves goes:
  an arc about its axis through the centre of what it carries (revolute), or a segment along its
  axis (prismatic), with both limits written and a tick at the file pose.
- **Gripper site:** the closing axis through the grasp centre, and the box GRIP closes on, dashed.
  inspect gives the box from `grip_box()` in checks/grip.py, so it is the check's own box.
- **Scene:** the floor as a grid at the run's floor height, and the world axes in a corner. A
  wheeled robot gets an arrow along +X from its driven axle: the front the wheeled checks expect.
- **Colours:** opened from a run, a joint with a failed measurement in red, a close one in amber,
  and the body it moves tinted the same. A click on a joint selects its row in the joints table,
  and a click on a row selects the joint.
- **Moving the view:** drag to turn, Shift+drag to move, the wheel to zoom, double-click to reset.
- **Docked:** when the page scrolls past the view, a smaller view stays in the bottom right corner,
  with the selected joint's name, so a joint picked in a table below shows at once. "Full view"
  scrolls back up; "×" closes it until the next pick. The view keeps its place on the page, so the
  page does not jump.
- The view shows the file pose. When a run has a replay, the same view also plays the motion of
  each check (section 6.11).

### 6.7 Compare (phase 1)

Two or more runs side by side: verdicts, and with measurements, the values and their differences.

- **Same asset:** the GUI matches runs by the SHA-256 of the root file, and says so when it
  differs. The hash does not cover the layers the root file references, so an equal hash does not
  prove an equal asset. The GUI says that too.
- **Different spec versions:** spec.md says that results of different spec versions are not
  compared. The GUI shows them side by side, marks no differences, and says why.
- **PhysX and Newton:** the usual case. Every Newton column carries the note "experimental: results
  can differ from run to run".
- **Newton repeats:** for each measurement, the lowest and highest value, and the verdicts counted
  ("PASS in 3 of 5"). A verdict that differs between repeats gets a mark.

### 6.8 Report (phase 1)

- **Files:** one HTML file that holds its CSS and data, and opens without the GUI or a network. A
  CSV with one row per run and check (verdict, detail), and one row per measurement when there are
  measurements.
- **Content:** versions, SHA-256, settings and their differences from the spec, notes, every
  verdict with its detail, every `N/A` with its reason. The report leaves out nothing from
  `results.json`, and adds no verdict of its own. A run with `engine_cannot_run` carries
  "N not run" and the checks' names next to its result, in the matrix and in its section, and a run
  with `wheels_without_mobile` carries "wheels not checked".
- **Paths:** `results.json` holds the full path of the asset, which can hold a user name. The report
  shows the file name only, unless the user asks for full paths.
- **Replay:** the report says that a run has a replay, and leaves the motion out. A replay can be
  18 MB (section 5.5), and the report must stay one file that opens by itself.
- **Look:** that of the reports on proofmass.com, for a report that goes to a customer. The file
  carries the logo and the latin files of the fonts, so it looks the same on any computer.

### 6.9 Settings (phase 2, built)

The Python of each engine, with a button that saves and tests it (section 4.1), and the workspace.
A note says that Isaac Sim asks for its licence the first time it starts, and that the GUI never
accepts it: the user starts Isaac Sim once in a terminal. The "close" level for margins is fixed
at 0.8 for now.

### 6.10 Experiments (open)

In the audits, values were changed by hand and the asset run again: joint friction set to 0, a
drive's max force times 100. proofmass-check never changes a setting to make a check pass, so such
an experiment must stay apart from the checks. If it is built:

- The change goes into a session layer over the asset. The file on disk never changes.
- The results go into a folder marked as an experiment, with every change listed.
- A report or a comparison never shows an experiment without that mark.

Whether to build it, and where, is open (section 11).

### 6.11 Replay (phase 4)

The motion of each check, from `replay.bin` (section 5.5), in the 3D view of the inspector (section
6.6). The colliders come from `inspect`, as before. So the replay needs the same Python with pxr as
the inspector (section 4.1).

- **Opening it:** the play button of a measurement row in the asset view (section 6.4) opens the
  inspector of the run, selects the row's joint, and plays the clips of that measurement. These
  are the clips of the measurement's check with its subject and case. When there are none, they
  are the clips of its check with an empty subject: the one clip of HOLD or DROP, or the 50 of
  STABLE.
- **The clips:** a list below the view, grouped by check, in the order they ran. Each clip shows
  its subject, case, attempt, length and `ok` as a sign. A filter shows only the clips that are
  not ok, such as the unstable poses of STABLE or the load at which the grip slipped.
- **Controls:** play and pause (Space), a time bar to drag, one frame back or forward (← and →),
  the previous or next clip, a speed from 0.1× to 2× of the simulated time, and loop.
- **Time:** each frame has its time. So the player shows the frame of the current time, and leaves
  out a frame that it cannot draw in time. A large asset then plays at the right speed with fewer
  frames.
- **What it draws:** the colliders at the pose of each frame. The view keeps each collider's
  triangles in its body's frame and moves them with the body. A joint's marks move with its first
  body (body0). For each operation, also:
  - settle and move: the clip's joint selected, with its target as a tick on its range;
  - push: an arrow about or along the joint's axis, with the effort;
  - trial: the grip box as a solid box, and the pull as an arrow with the load. In SHAKE, the
    arrow follows the force;
  - drive: the path of the root body on the floor, and the +X arrow.
- **Text in the view:** the check, subject, case and attempt, the time, and at the last frame the
  measurement's value and limit with its sign.
- **Values that are not finite:** the view stops at the last finite frame, and says from which
  time the engine gave values that are not finite.
- **Camera:** a clip starts with a view that holds all its frames, so a robot that drives 2 m
  stays in the view. The user moves the view as before, while the clip plays.
- **Docked:** the docked view (section 6.6) keeps playing.
- **Which run:** the GUI plays a replay only when its id is the one in `results.json` (section
  5.5). The inspector reads the asset as it is now. When its SHA-256 is not the run's, the view
  says that the colliders can differ from those of the run. A body of the replay that the asset
  no longer has is not drawn, and the view says so.
- **Newton:** a replay is one run of Newton, and another run can differ (spec.md section 5). The
  Newton note stays above the view.
- **Server:** `GET /api/replay?folder=…&run=…` sends the replay of a run. It takes the name from
  `replay.file` in `results.json`. The name must be a file name only, without a folder or "..",
  and the file must be in the folder of the results file.

## 7. How results are shown

- **Units:** degrees and millimetres for joints, as spec.md section 1 says for reports. m/s, kg, N
  and N m elsewhere. The files stay in SI units, and the GUI converts only what it shows.
- **Digits:** as many as the detail line gives for the same value. A failing value is never
  rounded so that it looks equal to its limit.
- **Verdicts:** a word or a sign together with a colour. `N/A` is grey, and never counts as a
  failure.
- **Newton:** the note from section 6.7 on every Newton run.
- **Settings:** a banner on every screen of a run whose settings are not the spec's.
- **Errors:** the error from `results.json`, and the last lines of `run.log`.
- Light and dark themes. The matrix and the tables work with the keyboard.
- **Look:** that of proofmass.com and its reports: the Proofmass logo, Archivo for text and
  headings, IBM Plex Mono for codes and values, one safety orange, square corners and 1 px rules.
  The fonts come with the package and from the page's own server (SIL OFL 1.1, see NOTICE), so
  the page still loads nothing from another computer.

## 8. Phases

| Phase | GUI | proofmass-check | Done when |
|---|---|---|---|
| 1. Viewer | server, batches, batch view, asset view, compare, report | 5.1 measurements. The viewer also works without them. | it opens the Lightwheel and AgiBot result folders, compares PhysX with Newton, and exports a report |
| 2. Runner | new batch, live progress, settings | 5.2 events, 5.4 several assets | a batch of 10 assets runs from the GUI in PhysX and Newton, can be cancelled, and gives the same `results.json` as the command line |
| 3. Inspector and 3D | inspector, 3D view | 5.3 inspect | the inspector shows the plan before a run, and the 3D view marks the joints that fail |
| 4. Replay | the replay in the inspector, the play button, the batch option | 5.5 the replay | a run of the G2 in PhysX and in Newton plays every clip, `results.json` is the same with and without `--replay` (in Newton, the verdicts), and the cost of recording is measured |
| 5. Experiments | after the decision in section 11 | | |

Phases 1 to 3 are built. Phase 2 was tested with a fake worker (section 9). Its "done when", a
batch of 10 assets in PhysX and Newton, is still to run on the real engines. Phase 3 was tested on
the test assets of `tests/usd_assets.py`, not yet on a large package such as the G2. Phase 4 is
designed (sections 5.5 and 6.11) and not built.

## 9. Tests

- **Server:** pytest, in CI, without a GPU. The API, the token and Origin checks, which files it
  serves, the workspace layout, and reading `results.json` with and without measurements.
- **Fixtures:** `results.json` files from runs with `tests/fake_engine.py`, one run that stopped
  with an error, and one where every check is `N/A`.
- **Workers:** `tests/fake_worker.py` writes events and results as `run` does, so no engine is
  needed. It can crash in the middle of an asset, or wait to be cancelled.
- **Changes in section 5:** unit tests as for any change, and the GPU tests for 5.4.
- **Replay:** the fake engine records frames, so CI tests the file (header, offsets, sizes), that
  each clip of each check has a label, and that each measurement finds its clips. A test runs
  each check with the fake engine with and without `--replay`, and compares `results.json`
  without `seconds` and `replay`. The GPU tests do the same in both engines: in Newton they
  compare the verdicts only (section 5.4).
- **Front end:** open (section 11).

## 10. Not in this design

- Editing the USD, or fixing an asset.
- Render meshes in the replay. The frames of `replay.bin` could become a USD layer of time samples
  over the asset, so that usdview or Isaac Sim plays a check with the asset's own meshes. That can
  come later, from the same file.
- Two replays side by side, such as PhysX and Newton for one measurement.
- Engines in the browser. proofmass-lab runs MuJoCo in the browser for lessons, not for checks.
- An Isaac Sim extension. It would tie the GUI to PhysX.
- Shared or remote use.

## 11. Open decisions

| Decision | Options | Recommendation |
|---|---|---|
| Which user comes first | the auditor, or the asset maker | the auditor. The batch view and compare serve both users, and the audits are the work done now. |
| Experiments | in this package, in proofmass-lab, or not at all | decide before phase 5 |
| Replay ticked by default in a new batch | ticked, or not | ticked, if recording adds less than 10 % to a run of the G2 in both engines (phase 4 measures it) |
| The command's name | `gui`, `view` or `serve` | `gui` |
| Front-end tests | Playwright (adds Node to the tools for development), or by hand | by hand in phase 1, then decide |
| Public reports | the report of section 6.8 is also the template for reports on proofmass.com, or not | decide in phase 1 |
