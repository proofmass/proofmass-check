# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Which checks run on an asset, and why the others do not.

The plan depends on the asset, the run's settings and the checks the engine supports. It never
depends on what the engine measures, so every engine gets the same plan for the same asset.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from proofmass_check.checks import TITLES
from proofmass_check.checks.grip import choose_site
from proofmass_check.checks.passive import passive_joints
from proofmass_check.model import Asset, GripperSite, Joint
from proofmass_check.rules import Settings


@dataclass(frozen=True)
class Plan:
    skip: Mapping[str, str]  # check ID: why it does not run
    driven: tuple[Joint, ...]  # joints with a position drive
    limited: tuple[Joint, ...]  # driven joints with both limits
    speed_limited: tuple[Joint, ...]  # limited driven joints with a speed limit
    passive: tuple[Joint, ...]  # joints PASSIVE pushes
    site: GripperSite | None  # the gripper site GRIP tests
    notes: tuple[str, ...]
    engine_cannot_run: tuple[str, ...] = ()  # checks the asset needs that the engine cannot run yet

    def runs(self, check_id: str) -> bool:
        return check_id not in self.skip


def make_plan(
    asset: Asset, engine: str, supported: Collection[str], settings: Settings, excluded: Collection[str] = ()
) -> Plan:
    """excluded: joints the engine cannot drive or measure one by one. No check tests them."""
    driven = tuple(j for j in asset.joints if j.moves and j.drive_kind == "position" and j.name not in excluded)
    limited = tuple(j for j in driven if j.limited)
    speed_limited = tuple(j for j in limited if 0 < j.max_speed < float("inf"))
    passive = tuple(j for j in passive_joints(asset) if j.name not in excluded)
    site, notes = choose_site(asset)

    has_drives = any(j.moves and j.drive_kind == "position" for j in asset.joints)  # excluded joints count here
    skip = (
        _drop_skip(asset, has_drives, settings)
        | _drive_skips(driven, limited, speed_limited)
        | _wheel_skips(asset, settings)
    )
    if not passive:
        skip["PASSIVE"] = "no joint without a position drive has limits"
    if site is None:
        why = "; ".join(notes) if notes else "the asset has no gripper site (gripper_maxOpening)"
        skip["GRIP"] = skip["SHAKE"] = why
        notes = []
    cannot = tuple(c for c in TITLES if c not in supported and c not in skip)
    for check_id in cannot:
        skip[check_id] = f"the {engine} engine cannot run this check on this asset yet"
    notes = list(notes)
    if cannot:  # a PASS does not cover these: the run must say so where a reader of the verdict looks
        notes.append(
            f"the {engine} engine cannot run {', '.join(cannot)} on this asset yet, so this result does not cover them"
        )
    rubbing = [f"{j.name} {j.physx_friction:g}" for j in asset.joints if j.moves and j.physx_friction > 0]
    if rubbing and engine != "physx":
        notes.append(
            f"only PhysX reads joint friction (physxJoint:jointFriction), so in the {engine} engine these "
            f"joints move without it: {', '.join(rubbing)}"
        )
    return Plan(skip, driven, limited, speed_limited, passive, site, tuple(notes), cannot)


def _drop_skip(asset: Asset, has_drives: bool, settings: Settings) -> dict[str, str]:
    if not settings.floor:
        return {"DROP": "the run has no floor (--no-floor)"}
    if asset.world_fixed:
        return {"DROP": f"the asset is fixed to the world by {', '.join(asset.world_fixed)}"}
    if asset.wheeled:
        return {"DROP": "a wheeled robot: STAND drops it instead"}
    if has_drives:
        return {"DROP": "the asset has position drives, so its joints are checked instead"}
    return {}


def _drive_skips(driven, limited, speed_limited) -> dict[str, str]:
    if not driven:
        return dict.fromkeys(("HOLD", "TRACK", "LIMIT", "STABLE", "SPEED"), "no joint has a position drive")
    if not limited:
        return dict.fromkeys(("TRACK", "LIMIT", "STABLE", "SPEED"), "no joint with a position drive has limits")
    if not speed_limited:
        return {"SPEED": "no joint with a position drive has a speed limit"}
    return {}


def _wheel_skips(asset: Asset, settings: Settings) -> dict[str, str]:
    wheel_checks = ("STAND", "DRIVE", "TURN", "STEER")
    if asset.wheeled is None:
        return dict.fromkeys(wheel_checks, "not a wheeled robot (no SimReady_Metadata.mobile)")
    if not settings.floor:
        return dict.fromkeys(wheel_checks, "the run has no floor (--no-floor)")
    if asset.wheeled.drive == "ackermann":
        return {"TURN": "an Ackermann robot turns by steering: see STEER"}
    return {"STEER": f"a {asset.wheeled.drive} robot does not steer: see TURN"}
