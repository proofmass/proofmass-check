# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The GUI's settings: the Python of each engine, and the workspace (docs/gui.md, sections 4.1 and 6.9).

Each engine runs in its own Python: PhysX in Isaac Sim's, Newton in one that has Newton. The GUI
never looks for them. The user gives their paths once, and the GUI keeps them in a file of the
user's own settings, not in the repository or the workspace.
"""

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from proofmass_check import engines

CHECK_SECONDS = 120  # the most a Python may take to print its version: a first start can be slow


def settings_file() -> Path:
    """%APPDATA%\\proofmass-check\\gui.json on Windows, ~/.config/proofmass-check/gui.json elsewhere."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "proofmass-check" / "gui.json"


@dataclass
class GuiSettings:
    pythons: dict[str, str] = field(default_factory=dict)  # engine name: the path of its Python
    workspace: str = str(Path.home() / "proofmass-check")  # where new batches go

    def python(self, engine: str) -> str:
        return self.pythons.get(engine, "")


def load(path: Path) -> GuiSettings:
    """The settings in the file, or the defaults when there is no file or it cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GuiSettings()
    if not isinstance(data, dict):
        return GuiSettings()
    pythons = data.get("pythons", {})
    settings = GuiSettings(
        pythons={k: str(v) for k, v in pythons.items() if k in engines.ENGINES} if isinstance(pythons, dict) else {}
    )
    if isinstance(data.get("workspace"), str) and data["workspace"].strip():
        settings.workspace = data["workspace"]
    return settings


def save(settings: GuiSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")


def check_python(python: str) -> tuple[bool, str]:
    """Run `<python> -m proofmass_check --version`: (it worked, what it printed or why it failed).

    This shows that the Python exists and has proofmass-check, and which version. It does not start
    the engine.
    """
    if not python:
        return False, "no Python set"
    if not Path(python).is_file():
        return False, f"no file {python}"
    try:
        done = subprocess.run(
            [python, "-m", "proofmass_check", "--version"],
            capture_output=True,
            text=True,
            timeout=CHECK_SECONDS,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"it did not answer in {CHECK_SECONDS} s"
    except OSError as e:
        return False, str(e)
    lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
    return done.returncode == 0, lines[-1] if lines else f"exit status {done.returncode}"
