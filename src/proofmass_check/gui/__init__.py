# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""The GUI: a local web page that shows the results of proofmass-check. docs/gui.md describes it.

runs.py reads results files and compares them, report.py writes them as HTML and CSV, and
server.py serves the page in static/. The GUI only shows what the checks decided.
"""
