# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""GRIP and SHAKE: the gripper holds its rated payload. This follows NVIDIA's FET028 test.

The fingers close on a box at the grasp centre. The box has no weight, so only the pull tests the
grip. A slip is the box moving along the pads. Motion along the closing axis is drift: two fingers
that each push with their force limit carry the box with them, and that is not a slip.
"""

from collections.abc import Sequence

import numpy as np

from proofmass_check import replay
from proofmass_check.checks import CheckResult, Measurement, judge, not_applicable
from proofmass_check.engines.base import Engine, GripBox, GripOutcome, GripSetup
from proofmass_check.geometry import apply, turn
from proofmass_check.model import Asset, GripperSite, Joint
from proofmass_check.rules import (
    GRIP_HOLD_S,
    GRIP_LOAD,
    GRIP_LOADS,
    GRIP_MIN_TRAVEL,
    GRIP_SLIP,
    GRIP_WIDTH,
    LIMIT_TOL,
    SHAKE_HZ,
    Settings,
)


def choose_site(asset: Asset) -> tuple[GripperSite | None, list[str]]:
    """The site GRIP tests, and a note for each site it does not test.

    GRIP tests the first site that has gripper_maxPayload, sits on a rigid body, and belongs to a
    gripper fixed to the world, or held by the checks (a free gripper would fall).
    """
    fixed = bool(asset.world_fixed) or asset.held
    found, notes = None, []
    for site in asset.sites:
        why = (
            "no gripper_maxPayload" if not site.payload
            else "not on a rigid body" if not site.body
            else "the gripper is not fixed to the world" if not fixed
            else f"GRIP tests one site, {found.name}" if found
            else None
        )  # fmt: skip
        if why:
            notes.append(f"gripper site {site.name}: {why}, so GRIP does not test it")
        else:
            found = site
    return found, notes


def closing_targets(asset: Asset, site: GripperSite) -> dict[str, float]:
    """The finger joints of a site, each with the limit that closes it.

    A finger joint is a limited, position-driven joint below the site's body. Its closing limit is
    the one that brings the bodies it moves nearer the grasp centre along the closing axis. A joint
    that moves them less than GRIP_MIN_TRAVEL along that axis does not close the gripper.
    The file pose is taken as each joint at its rest position.
    """
    below = set(asset.carried(site.body))
    targets = {}
    for joint in asset.joints:
        if joint.drive_kind != "position" or not joint.limited or joint.body0 not in below:
            continue
        moved = [asset.bodies[path] for path in asset.carried(joint.body1)]
        centre = np.mean([apply(b.pose, b.com) for b in moved], axis=0)
        gaps = {}
        for limit in (joint.lower, joint.upper):
            if joint.revolute:
                at_limit = joint.pivot + turn(centre - joint.pivot, joint.direction, limit - joint.rest)
            else:
                at_limit = centre + (limit - joint.rest) * joint.direction
            gaps[limit] = abs((at_limit - site.centre) @ site.closing)
        if abs(gaps[joint.lower] - gaps[joint.upper]) >= GRIP_MIN_TRAVEL:
            targets[joint.name] = min(gaps, key=gaps.get)
    return targets


def grip_box(site: GripperSite) -> GripBox:
    """The box: GRIP_WIDTH of the maximum opening across the pads, and the pad size in the other two directions."""
    rotation = np.column_stack([np.cross(site.line, site.forward), site.line, site.forward])
    return GripBox(size=(GRIP_WIDTH * site.opening, site.pad, site.pad), centre=site.centre, rotation=rotation)


def gripped(joints: Sequence[Joint], closed: dict[str, float], targets: dict[str, float], settings: Settings) -> bool:
    """True when the fingers stopped on the box: at least one finger short of its closing limit.

    One is enough. With two fingers on separate drives, one can carry the box until it meets its
    limit, and the other then holds the box against it. All fingers at their limits means the
    gripper closed past the box.
    """
    return any(abs(closed[j.name] - targets[j.name]) > LIMIT_TOL * settings.tolerance(j.revolute) for j in joints)


def grip_and_shake(engine: Engine, asset: Asset, site: GripperSite, settings: Settings) -> list[CheckResult]:
    targets = closing_targets(asset, site)
    if not targets:
        return [
            judge("GRIP", False, f"site {site.name}: no position drive closes the fingers"),
            not_applicable("SHAKE", "GRIP found no finger drive"),
        ]
    fingers = [asset.joint(name) for name in targets]
    hold = {j.name: j.rest for j in asset.joints if j.drive_kind == "position" and j.name not in targets}
    setup = GripSetup(
        site=site,
        box=grip_box(site),
        close=targets,
        hold=hold,
        close_seconds=settings.settle_s,
        pull_seconds=GRIP_HOLD_S,
        shake_hz=SHAKE_HZ,
    )
    scene = engine.grip_scene(setup)

    def held(outcome: GripOutcome) -> tuple[bool, str, float]:
        """Whether the grip held, in words, and how far the box slid along the pads (m)."""
        motion = np.asarray(outcome.motion, float)
        drift = float(abs(motion @ site.closing))
        slip = float(np.linalg.norm(motion - (motion @ site.closing) * site.closing))
        closed = gripped(fingers, outcome.closed, targets, settings)
        ok = outcome.finite and closed and slip < GRIP_SLIP
        words = f"slid {slip * 1000:.1f} mm" if slip < 0.1 else "the box is lost"
        if GRIP_SLIP <= drift < 0.1:
            words += f", drifted {drift * 1000:.1f} mm with the fingers"
        return ok, words + ("" if ok else " SLIP" if closed else " NOT GRIPPED"), slip

    payload = site.payload
    rows, measurements = [], []
    for label, direction in (("out of the fingers", site.forward), ("along the grip line", site.line)):
        best, tried = 0.0, []
        for fraction in GRIP_LOADS:
            with replay.label(site.name, label, f"{fraction * payload:g} kg") as clip:
                outcome = scene.trial(fraction * payload, direction, shake=False)
            ok, words, _ = held(outcome)
            clip.ok = ok
            tried.append(f"{fraction * payload:g} kg {words}")
            if not ok:
                break
            best = fraction
        rows.append(f"{label} holds {best * payload:g} kg ({', '.join(tried)})")
        measurements.append(
            Measurement(
                site.name,
                label,
                "highest load held",
                best * payload,
                GRIP_LOAD * payload,
                "kg",
                best >= GRIP_LOAD,
                "min",
            )
        )
    detail = f"site {site.name}, payload {payload:g} kg: " + "; ".join(rows)
    grip = judge("GRIP", all(m.ok for m in measurements), detail, measurements)
    with replay.label(site.name, check="SHAKE") as clip:
        outcome = scene.trial(GRIP_LOAD * payload, site.forward, shake=True)
    ok, words, slip = held(outcome)
    clip.ok = ok
    slipped = Measurement(site.name, "", "slip along the pads", slip, GRIP_SLIP, "m", ok)
    shake = judge("SHAKE", ok, f"{GRIP_LOAD * payload:g} kg at {SHAKE_HZ:g} Hz: {words}", [slipped])
    return [grip, shake]
