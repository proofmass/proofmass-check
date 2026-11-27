# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The GUI's scripts parse. A syntax error stops the whole page at "Loading…", and no Python test sees it."""

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "src" / "proofmass_check" / "gui" / "static"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="needs Node.js to parse JavaScript")
@pytest.mark.parametrize("script", sorted(p.name for p in STATIC.glob("*.js")))
def test_the_script_parses(script):
    """0.4.0 shipped app.js with an apostrophe inside a single-quoted string, and the GUI never loaded."""
    checked = subprocess.run([NODE, "--check", str(STATIC / script)], capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stderr
