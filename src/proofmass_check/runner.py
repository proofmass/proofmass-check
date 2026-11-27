# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""One run: every check on one asset in one engine."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from proofmass_check.checks import TITLES, CheckResult, not_applicable
from proofmass_check.checks.drop import drop
from proofmass_check.checks.grip import grip_and_shake
from proofmass_check.checks.inertia import inertia
from proofmass_check.checks.joints import hold, limit, stable, track
from proofmass_check.checks.load import built, load, with_engine_masses
from proofmass_check.checks.passive import passive
from proofmass_check.checks.speed import speed
from proofmass_check.checks.wheeled import wheeled
from proofmass_check.engines.base import Engine
from proofmass_check.geometry import run_floor
from proofmass_check.model import Asset
from proofmass_check.plan import Plan, make_plan
from proofmass_check.rules import BASE_LIFT, TRACK_AT, Settings

STATIC = ("INERTIA",)  # checks that read the file and run nothing


@dataclass(frozen=True)
class Run:
    asset: Asset
    engine: str
    engine_version: dict[str, str]
    settings: Settings
    floor: float | None  # m
    results: tuple[CheckResult, ...]
    notes: tuple[str, ...]
    seconds: float
    engine_cannot_run: tuple[str, ...] = ()  # checks the asset needs that the engine cannot run yet
    gripper_without_site: tuple[str, ...] = ()  # joints that look like fingers, with no gripper site
    wheels_without_mobile: tuple[str, ...] = ()  # joints that look like wheels, with no mobile description

    @property
    def passed(self) -> bool:
        """True when no check failed. A check that does not apply does not fail the run."""
        return all(r.verdict != "FAIL" for r in self.results)


def run_checks(engine: Engine, asset: Asset, settings: Settings, events: Callable | None = None) -> Run:
    """Run every check in the order of TITLES. The engine must be started and not yet opened.

    events, when given, is called as events(name, **fields) for the progress of the run: "check"
    when a check starts, "step" after each engine operation, "result" with each verdict, and "plan"
    once LOAD is done (events.py).
    """
    emit = events or (lambda name, **fields: None)
    start = time.monotonic()
    if engine.reads_mjc_actuators:
        asset = asset.with_mjc_drives()
    floor = run_floor(asset, settings)
    engine.open(asset, floor, BASE_LIFT if asset.wheeled else 0.0 if asset.held else None)
    emit("check", id="LOAD", total=None)
    outcome = engine.load()
    results = {"LOAD": load(asset, outcome)}
    emit("result", id="LOAD", verdict=results["LOAD"].verdict)
    plan = make_plan(asset, engine.name, engine.supported, settings, outcome.not_addressable)
    not_built = "the engine did not build the asset as the USD describes it (LOAD)"
    # INERTIA reads the file and runs nothing, so it runs whatever LOAD finds.
    static = [c for c in STATIC if plan.runs(c)]
    runs = [c for c in TITLES if c != "LOAD" and plan.runs(c)] if built(outcome) else static
    emit("plan", runs=runs, skip={c: plan.skip.get(c, not_built) for c in TITLES if c != "LOAD" and c not in runs})
    for check_id in static:
        emit("check", id=check_id, total=None)
        results[check_id] = inertia(asset)  # the file's masses, not the engine's
        emit("result", id=check_id, verdict=results[check_id].verdict)
    if built(outcome):
        counted = _Counted(engine, emit) if events else None
        results |= _run_planned(counted or engine, with_engine_masses(asset, outcome), plan, settings, floor, emit)
    for check_id in TITLES:
        if check_id not in results:
            results[check_id] = not_applicable(check_id, plan.skip.get(check_id, not_built))
    notes = list(plan.notes) + [f"settings differ from the spec: {change}" for change in settings.changes()]
    if outcome.not_addressable:
        names = ", ".join(outcome.not_addressable)
        notes.append(
            f"the {engine.name} engine cannot drive or measure these joints one by one yet, "
            f"so no check tests them: {names}"
        )
    return Run(
        asset=asset,
        engine=engine.name,
        engine_version=dict(engine.version()),
        settings=settings,
        floor=floor,
        results=tuple(results[check_id] for check_id in TITLES),
        notes=tuple(notes),
        seconds=round(time.monotonic() - start, 1),
        engine_cannot_run=plan.engine_cannot_run,
        gripper_without_site=plan.gripper_without_site,
        wheels_without_mobile=plan.wheels_without_mobile,
    )


def _run_planned(engine: Engine, asset: Asset, plan: Plan, settings: Settings, floor: float | None, emit: Callable):
    # Each step gives one or more results. GRIP also gives SHAKE, because both use the same grip scene.
    steps = {
        "DROP": lambda: [drop(engine, asset, floor)],
        "HOLD": lambda: [hold(engine, plan.driven, settings)],
        "TRACK": lambda: [track(engine, plan.driven, plan.limited, settings)],
        "LIMIT": lambda: [limit(engine, plan.driven, plan.limited, settings)],
        "STABLE": lambda: [stable(engine, plan.driven, plan.limited, settings)],
        "SPEED": lambda: [speed(engine, plan.driven, plan.speed_limited, settings)],
        "PASSIVE": lambda: [passive(engine, asset, plan.passive, settings)],
        "GRIP": lambda: grip_and_shake(engine, asset, plan.site, settings),
        **{
            check_id: (lambda c=check_id: [wheeled(engine, asset, c)])
            for check_id in ("STAND", "DRIVE", "TURN", "STEER")
        },
    }
    results: dict[str, CheckResult] = {}
    for check_id, step in steps.items():
        if plan.runs(check_id):
            total = _operations(check_id, plan, settings)
            if isinstance(engine, _Counted):
                engine.start(check_id, total)
            emit("check", id=check_id, total=total)
            for result in step():
                if plan.runs(result.id):
                    results[result.id] = result
                    emit("result", id=result.id, verdict=result.verdict)
    return results


def _operations(check_id: str, plan: Plan, settings: Settings) -> int | None:
    """How many engine operations a check makes, for its progress. None when it is not known.

    PASSIVE pushes again when a push does not reach the limit, and GRIP raises the load until the
    box slips, so their counts are known only at the end.
    """
    return {
        "DROP": 1,
        "HOLD": 1,
        "TRACK": len(TRACK_AT) * len(plan.limited),
        "LIMIT": len(plan.limited),
        "STABLE": settings.random_poses,
        "SPEED": len(plan.speed_limited),
        "STAND": 1,
        "DRIVE": 1,
        "TURN": 1,
        "STEER": 1,
    }.get(check_id)


class _Counted:
    """The engine, with each operation it runs counted for the "step" events.

    The checks get it in place of the engine. Every other attribute is the engine's own.
    """

    OPERATIONS = frozenset({"drop", "settle", "move", "push", "drive"})

    def __init__(self, engine: Engine, emit: Callable):
        self._engine, self._emit = engine, emit
        self._check_id, self._total, self._done = "", None, 0

    def start(self, check_id: str, total: int | None) -> None:
        self._check_id, self._total, self._done = check_id, total, 0

    def step(self) -> None:
        self._done += 1
        self._emit("step", id=self._check_id, done=self._done, total=self._total)

    def __getattr__(self, name: str):
        attribute = getattr(self._engine, name)
        if name in self.OPERATIONS:
            return self._counting(attribute)
        if name == "grip_scene":
            return lambda setup: _CountedScene(attribute(setup), self)
        return attribute

    def _counting(self, operation: Callable) -> Callable:
        def counted(*args, **kwargs):
            outcome = operation(*args, **kwargs)
            self.step()
            return outcome

        return counted


class _CountedScene:
    """A grip scene, with each trial counted."""

    def __init__(self, scene, counter: _Counted):
        self._scene, self._counter = scene, counter

    def trial(self, *args, **kwargs):
        outcome = self._scene.trial(*args, **kwargs)
        self._counter.step()
        return outcome

    def __getattr__(self, name: str):
        return getattr(self._scene, name)
