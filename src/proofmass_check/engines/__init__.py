# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
"""The engines proofmass-check can run on.

An engine runs in the Python environment that has it installed. proofmass-check does not look
for other Python environments: run it in the one that has Isaac Sim, or in the one that has Newton.
"""

import importlib
import sys

from proofmass_check.engines.base import Engine

ENGINES = {
    "physx": ("proofmass_check.engines.physx", "Isaac Sim 6.1 (see NVIDIA's guide to installing Isaac Sim with pip)"),
    "newton": ("proofmass_check.engines.newton", 'Newton (pip install "newton[sim,importers]")'),
}


class EngineUnavailableError(RuntimeError):
    """The engine cannot run in this Python environment."""


def create(name: str) -> Engine:
    """Start an engine. For PhysX this starts Isaac Sim, which can take a minute the first time."""
    module_name, needs = ENGINES[name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name == module_name:
            raise EngineUnavailableError(f"the {name} engine is not in this version of proofmass-check yet") from e
        raise EngineUnavailableError(f"the {name} engine needs {needs} in this Python ({sys.executable}): {e}") from e
    return module.create()
