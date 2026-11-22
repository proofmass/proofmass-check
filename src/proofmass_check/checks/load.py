# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""LOAD: the engine builds every joint, and the same total mass as the USD."""

import dataclasses

from proofmass_check.checks import CheckResult, Measurement, judge
from proofmass_check.engines.base import LoadOutcome
from proofmass_check.model import Asset
from proofmass_check.rules import MASS_TOL


def built(outcome: LoadOutcome) -> bool:
    """True when the engine and the USD have the same joints. Other checks need this."""
    return not outcome.missing and not outcome.unknown


def load(asset: Asset, outcome: LoadOutcome) -> CheckResult:
    given = [b.mass for b in asset.bodies.values()]
    usd_mass = sum(given) if all(given) else None  # only when the USD gives every mass
    engine_mass = sum(outcome.masses.values())
    moving = [j for j in asset.joints if j.moves]
    position = sum(j.drive_kind == "position" for j in moving)
    velocity = sum(j.drive_kind == "velocity" for j in moving)
    detail = f"{len(moving)} joints ({position} position, {velocity} velocity drives), "
    detail += f"mass in the engine {engine_mass:.2f} kg"
    if usd_mass is None:
        detail += f" (the USD gives it for {sum(map(bool, given))} of {len(given)} bodies)"
    else:
        detail += f", in the USD {usd_mass:.2f} kg"
    if outcome.missing:
        detail += f"; joints the engine did not build: {list(outcome.missing)}"
    if outcome.unknown:
        detail += f"; engine joints that are not in the USD: {list(outcome.unknown)}"
    mass_ok = usd_mass is None or abs(engine_mass - usd_mass) <= MASS_TOL * usd_mass
    measurements = [
        Measurement("", "", "joints the engine did not build", len(outcome.missing), 0, "1", not outcome.missing),
        Measurement("", "", "engine joints not in the USD", len(outcome.unknown), 0, "1", not outcome.unknown),
    ]
    if usd_mass is not None:
        difference = abs(engine_mass - usd_mass) / usd_mass
        measurements.append(Measurement("", "", "mass difference", difference, MASS_TOL, "1", mass_ok))
    return judge("LOAD", built(outcome) and mass_ok, detail, measurements)


def with_engine_masses(asset: Asset, outcome: LoadOutcome) -> Asset:
    """The asset with the engine's mass and centre of mass for each body whose mass the USD leaves out.

    PASSIVE and GRIP need every mass, and only the engine knows the ones it computes itself.
    """
    bodies = {
        path: body
        if body.mass is not None or path not in outcome.masses
        else dataclasses.replace(body, mass=outcome.masses[path], com=outcome.coms.get(path, body.com))
        for path, body in asset.bodies.items()
    }
    return dataclasses.replace(asset, bodies=bodies)
