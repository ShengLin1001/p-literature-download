#!/usr/bin/env python
"""Run the canonical official-only downloader wrapper from this test directory."""

import runpy
import sys
from pathlib import Path


SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "publisher-official-pdf/scripts"
)
sys.path.insert(0, str(SCRIPT_DIR))
runpy.run_path(str(SCRIPT_DIR / "pdf_download.py"), run_name="__main__")
