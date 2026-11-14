# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
"""docs/spec.md and rules.py must give the same numbers."""

import ast
import re
from pathlib import Path

import pytest

from proofmass_check import rules

SPEC = (Path(__file__).parent.parent / "docs" / "spec.md").read_text(encoding="utf-8")
# `NAME` = 0.5, `NAME` = 1/60 or `NAME` = (0.25, 0.75)
WRITTEN = dict(re.findall(r"`([A-Z][A-Z0-9_]+)` = (\([0-9., ]+\)|[0-9]+/[0-9]+|[0-9][0-9.]*)", SPEC))
NUMBERS = {
    name: value
    for name, value in vars(rules).items()
    if name.isupper() and isinstance(value, int | float | tuple) and name != "SPEC_VERSION"
}


def number(text: str):
    if "/" in text and not text.startswith("("):
        top, bottom = text.split("/")
        return int(top) / int(bottom)
    return ast.literal_eval(text.rstrip("."))


@pytest.mark.parametrize("name", sorted(NUMBERS))
def test_every_number_is_in_the_spec(name):
    assert name in WRITTEN, f"docs/spec.md does not give {name}"
    assert number(WRITTEN[name]) == pytest.approx(NUMBERS[name])


def test_the_spec_names_no_unknown_number():
    assert set(WRITTEN) <= set(NUMBERS)


def test_the_spec_version():
    assert f"Version {rules.SPEC_VERSION} " in SPEC
