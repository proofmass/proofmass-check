# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""What each engine reads and can run, known without starting it.

`inspect` makes the plan of an asset without an engine (docs/gui.md, section 5.3). The engine
modules import their engine at the top (isaacsim, newton), so these facts live here, and the
engines take them from here. So the plan of `inspect` and the plan of a run cannot differ in them.
"""

from dataclasses import dataclass

from proofmass_check.checks import TITLES
from proofmass_check.model import Asset

WHEELED = frozenset({"STAND", "DRIVE", "TURN", "STEER"})


@dataclass(frozen=True)
class Capabilities:
    variant_sets: tuple[str, ...]  # the asset's variant sets this engine reads, preferred first
    reads_mjc_actuators: bool  # a joint without PhysicsDriveAPI takes the drive of its MjcActuator


CAPABILITIES = {
    "physx": Capabilities(variant_sets=("PhysX",), reads_mjc_actuators=False),  # Isaac Sim reads no MjcActuator
    "newton": Capabilities(variant_sets=("Newton", "MuJoCo"), reads_mjc_actuators=True),  # as Newton's importer
}


def supported(engine: str, asset: Asset | None = None) -> frozenset[str]:
    """The checks an engine can run on an asset, as far as the asset alone tells.

    INERTIA reads the file, so every engine runs it. PhysX runs the drive and grip checks only on an
    articulation. Newton cannot run SPEED or the wheeled checks yet. A Newton model with no free joint
    also has no DROP, and only the built model tells that, so the Newton engine leaves it out itself.
    """
    if engine == "physx" and asset is not None and not asset.articulated:
        return frozenset({"LOAD", "INERTIA", "DROP", "PASSIVE"})
    if engine == "newton":
        return frozenset(TITLES) - {"SPEED"} - WHEELED
    return frozenset(TITLES)
