# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
"""One run: every check on one asset in one engine."""

import time
from dataclasses import dataclass

from proofmass_check.checks import TITLES, CheckResult, not_applicable
from proofmass_check.checks.drop import drop
from proofmass_check.checks.grip import grip_and_shake
from proofmass_check.checks.joints import hold, limit, stable, track
from proofmass_check.checks.load import built, load, with_engine_masses
from proofmass_check.checks.passive import passive
from proofmass_check.checks.speed import speed
from proofmass_check.checks.wheeled import wheeled
from proofmass_check.engines.base import Engine
from proofmass_check.geometry import floor_height
from proofmass_check.model import Asset
from proofmass_check.plan import Plan, make_plan
from proofmass_check.rules import BASE_LIFT, Settings


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

    @property
    def passed(self) -> bool:
        """True when no check failed. A check that does not apply does not fail the run."""
        return all(r.verdict != "FAIL" for r in self.results)


def run_checks(engine: Engine, asset: Asset, settings: Settings) -> Run:
    """Run every check in the order of TITLES. The engine must be started and not yet opened."""
    start = time.monotonic()
    floor = floor_height(asset.bodies.values()) if settings.floor else None
    engine.open(asset, floor, BASE_LIFT if asset.wheeled else None)
    outcome = engine.load()
    results = {"LOAD": load(asset, outcome)}
    plan = make_plan(asset, engine.name, engine.supported, settings, outcome.not_addressable)
    if built(outcome):
        results |= _run_planned(engine, with_engine_masses(asset, outcome), plan, settings, floor)
    for check_id in TITLES:
        if check_id not in results:
            results[check_id] = not_applicable(
                check_id, plan.skip.get(check_id, "the engine did not build the asset as the USD describes it (LOAD)")
            )
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
    )


def _run_planned(engine: Engine, asset: Asset, plan: Plan, settings: Settings, floor: float | None):
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
            results |= {result.id: result for result in step() if plan.runs(result.id)}
    return results
