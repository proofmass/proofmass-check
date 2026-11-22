# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The checks: what each one measures and how it decides PASS or FAIL.

Each check asks the engine for a few measurements (engines/base.py) and judges them against the
numbers in rules.py. No check knows which engine it runs on.
"""

from dataclasses import dataclass
from typing import Literal

from proofmass_check import rules

Verdict = Literal["PASS", "FAIL", "N/A"]

# Every check, in the order a run reports them, with a one-line title.
TITLES = {
    "LOAD": "the engine builds the asset as the USD describes it",
    "DROP": f"dropped from {rules.DROP_HEIGHT * 100:g} cm, comes to rest on the floor",
    "HOLD": "drives hold the rest pose under gravity",
    "TRACK": f"each drive reaches {rules.TRACK_AT[0]:.0%} and {rules.TRACK_AT[1]:.0%} of its range",
    "LIMIT": "joint limits stop a drive commanded past them",
    "STABLE": f"stable in {rules.RANDOM_POSES} random poses inside the limits",
    "SPEED": f"at a {1 / rules.SPEED_DT:.0f} Hz physics step, each drive stays under its speed limit",
    "PASSIVE": "each joint without a drive, when pushed, reaches both limits and stops there",
    "GRIP": f"holds {rules.GRIP_LOAD:.0%} of gripper_maxPayload pulled two ways",
    "SHAKE": f"holds {rules.GRIP_LOAD:.0%} of gripper_maxPayload shaken at up to 2 g",
    "STAND": f"dropped from {rules.DROP_HEIGHT * 100:g} cm with its wheels braked, stands upright and still",
    "DRIVE": "all driven wheels forward: drives straight along +X at the commanded speed",
    "TURN": "wheels in opposite directions: turns in place at the expected rate",
    "STEER": f"steered to {rules.STEER_FRACTION:.0%} of its range: drives a circle of the Ackermann radius",
}


@dataclass(frozen=True)
class Measurement:
    """One number that a check compared with its rule (docs/spec.md, section 6).

    value and limit are in SI units. With bound "max" the rule wants value <= limit, with "min"
    value >= limit. limit is None for a number the check reports but does not judge, such as the
    tilt after DROP. ok is what the check decided for this number. The check sets it with the same
    comparison that decides its verdict, which can need more than the number: finite values, too.
    """

    subject: str  # a joint, a gripper site, or "" for the whole asset
    case: str  # which test of the subject: "25%", "upper", "out of the fingers", or ""
    quantity: str
    value: float
    limit: float | None
    unit: str  # "m", "rad", "m/s", "rad/s", "kg", "N", "N m", or "1" for a count or a fraction
    ok: bool
    bound: Literal["max", "min"] = "max"


@dataclass(frozen=True)
class CheckResult:
    id: str
    verdict: Verdict
    detail: str
    measurements: tuple[Measurement, ...] = ()

    @property
    def title(self) -> str:
        return TITLES[self.id]


def judge(check_id: str, ok: bool, detail: str, measurements=()) -> CheckResult:
    return CheckResult(check_id, "PASS" if ok else "FAIL", detail, tuple(measurements))


def not_applicable(check_id: str, reason: str) -> CheckResult:
    return CheckResult(check_id, "N/A", reason)
