# SPDX-FileCopyrightText: 2026 The proofmass-check authors
# SPDX-License-Identifier: Apache-2.0
"""Lets `python -m proofmass_check` work like the `proofmass-check` command."""

import sys

from proofmass_check.cli import main

sys.exit(main())
