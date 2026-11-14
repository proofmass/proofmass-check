# Contributing

Thank you for helping. This page says how the project is built, how to change it, and how we
write code and comments.

## Set up

You need [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

These need no GPU and no engine. They run in CI on Linux and Windows.

## How the code is built

| Module | What it does |
|---|---|
| `usd_reader.py` | reads the USD into the classes of `model.py`, in SI units |
| `model.py` | `Asset`, `Body`, `Joint`, `GripperSite` |
| `rules.py` | every number of the spec, in one place |
| `plan.py` | which checks apply to an asset, and why the others do not |
| `checks/` | one module per check: what it asks the engine, and how it decides |
| `engines/base.py` | the `Engine` protocol: the operations an engine must give |
| `engines/<name>.py` | one engine adapter |
| `runner.py` | runs the plan on one engine |
| `report.py` | writes `results.json` |

An engine only simulates. It never decides which checks run or whether they pass. This keeps the
engines comparable: a different result in two engines comes from the engines, not from our code.

## Changing a rule or a number

A rule or a number is part of the spec. To change one:

1. Change `rules.py` and `docs/spec.md` together. `tests/test_spec.py` fails when they differ.
2. Raise `SPEC_VERSION` in `rules.py`.
3. Add a line to `CHANGELOG.md` that says what changed and why.
4. In the pull request, say which engine, engine version and assets you ran it on, and what changed
   in their results.

## Adding a check

1. Write down the rule in `docs/spec.md` first: what it checks in one sentence, why, the setup and
   the pass rule.
2. Add the module in `checks/`, its title in `checks/__init__.py`, and when it applies in `plan.py`.
3. If the check needs a new engine operation, add it to `engines/base.py` and to every engine. An
   engine that cannot do it yet leaves the check out of its `supported` set, and the plan reports
   `N/A`.
4. Add unit tests with `tests/fake_engine.py`.

## Adding an engine

Implement the `Engine` protocol in `engines/base.py` in a new module with a `create()` function,
and add it to `ENGINES` in `engines/__init__.py`. Import the engine's own packages inside that
module only.

## Tests that need a GPU

Tests that run a real engine have the `gpu` marker and are in `tests/test_engines_gpu.py`. They do
not run in CI. Run them in the engine's Python environment, with pytest installed there:

```bash
pytest tests/test_engines_gpu.py -m gpu --engine physx
```

```bash
pytest tests/test_engines_gpu.py -m gpu --engine newton
```

Give the file name: the other test files import pxr when pytest collects them, and in Isaac Sim
pxr exists only after Isaac Sim has started. Isaac Sim ends the process when it closes, so
`conftest.py` closes the engine after pytest's summary, with pytest's exit status.

Run them for every change to an engine adapter or to a check, and say in the pull request which
engine versions you used.

## How we write comments

Write for a person who knows Python and physics, but not this code.

- Say why, not what. The code already says what.
- One idea per sentence. Split a sentence that has a semicolon or a second colon.
- Give the unit every time: m, kg, s, rad, N, N m.
- Use one name for one thing. A "joint" is not also an "axis" or a "DOF" in the next line.
- When a rule comes from somewhere, name it: an NVIDIA rule ID, a section of the spec, an engine
  issue.
- No history ("changed on...", "used to..."). Git and `CHANGELOG.md` keep history.
- No notes to yourself ("kept", "hack", "see above"). Write the full sentence.
- A docstring starts with what the function returns or does, in one sentence. Details follow as
  short sentences or a list.

Before: `# kept: its prims expire with it`
After: `# Keep a reference to the stage. Its prims become invalid when the stage is freed.`

## Code style

- `ruff` formats and lints the code. Lines are at most 120 characters.
- Type hints on functions that other modules call.
- Full names for values that travel between functions (`settings`, not `st`). Short names are
  fine inside a few lines.
- Every file starts with the two SPDX lines (copyright and license).

## Pull requests

- One change per pull request. The title says what changes, for example "PASSIVE: push from the
  handle of a revolute joint".
- We merge with squash, so the title becomes the commit message.
- By sending a pull request, you agree that your contribution is licensed under Apache-2.0.
