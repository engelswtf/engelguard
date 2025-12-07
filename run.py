#!/usr/bin/env python3
"""
Simple runner script for the Twitch bot.

Usage:
    python run.py

Or make executable:
    chmod +x run.py
    ./run.py
"""

import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from bot import main

if __name__ == "__main__":
    main()
