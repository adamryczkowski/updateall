#!/usr/bin/env python
"""Debug script to run the update-all app with interactive mode.

This script is designed to be run under the PDB debugger to investigate
the phase counter reset issue.

Usage:
    cd /home/adam/tmp/updateall/cli
    poetry run python ../scripts/debug_app.py
"""

import sys
import os

# Add the cli directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cli"))

# Import and run the app
from cli.main import app

if __name__ == "__main__":
    # Simulate: update-all run -i -p mock-alpha -p mock-beta
    sys.argv = [
        "update-all",
        "run",
        "-i",
        "-p",
        "mock-alpha",
        "-p",
        "mock-beta",
    ]
    app()
