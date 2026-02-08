"""Tests for dev CLI entry point."""

from __future__ import annotations

import subprocess
import sys


class TestCLI:
    def test_no_args_exits_1(self):
        result = subprocess.run(
            [sys.executable, "-m", "paper_search"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_no_args_prints_usage(self):
        result = subprocess.run(
            [sys.executable, "-m", "paper_search"],
            capture_output=True,
            text=True,
        )
        assert "Usage:" in result.stderr
