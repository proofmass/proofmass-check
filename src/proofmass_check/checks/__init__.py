# SPDX-FileCopyrightText: 2026 The proofmass-check authors
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
class CheckResult:
    id: str
    verdict: Verdict
    detail: str

    @property
    def title(self) -> str:
        return TITLES[self.id]


def judge(check_id: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(check_id, "PASS" if ok else "FAIL", detail)


def not_applicable(check_id: str, reason: str) -> CheckResult:
    return CheckResult(check_id, "N/A", reason)
