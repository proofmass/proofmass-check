# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""Joint values as people read them: degrees for an angle, millimetres for a short distance."""

import math

from proofmass_check.model import Joint


def error(joint: Joint, value: float) -> str:
    """A joint error or distance: "0.250 deg" or "1.20 mm"."""
    return f"{math.degrees(value):.3f} deg" if joint.revolute else f"{value * 1000:.2f} mm"


def speed(joint: Joint, value: float, digits: str = ".3g") -> str:
    """A joint speed without its unit: deg/s for a revolute joint, m/s for a prismatic one."""
    return format(math.degrees(value) if joint.revolute else value, digits)


def speed_unit(joint: Joint) -> str:
    return "deg/s" if joint.revolute else "m/s"


def effort_unit(joint: Joint) -> str:
    return "N m" if joint.revolute else "N"


def si_unit(joint: Joint) -> str:
    """The SI unit of a joint position, as a measurement in results.json gives it."""
    return "rad" if joint.revolute else "m"


def si_speed_unit(joint: Joint) -> str:
    return "rad/s" if joint.revolute else "m/s"
