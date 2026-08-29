#!/usr/bin/env python
"""Run the canonical p-pdf-download script from this local test directory."""

import runpy
import sys
from pathlib import Path


SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "publisher-official-pdf/scripts"
)
SCRIPT = SCRIPT_DIR / "auto_pdf_download.py"
sys.path.insert(0, str(SCRIPT_DIR))
runpy.run_path(str(SCRIPT), run_name="__main__")
