"""Regression tests for the ``python -m xenon`` entry point (issue #110).

On Windows the console script can land in a Scripts directory that is not on
``PATH``; ``python -m xenon`` must keep working regardless, because it does not
depend on ``PATH`` at all.
"""

from __future__ import annotations

import subprocess
import sys

import xenon


def test_python_dash_m_xenon_reports_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "xenon", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stderr
    assert xenon.__version__ in result.stdout


def test_module_entry_imports_cli() -> None:
    """The entry module must expose the same callable as the console script."""
    import xenon.__main__ as module_entry
    from xenon.main import cli as console_cli

    assert module_entry.cli is console_cli
