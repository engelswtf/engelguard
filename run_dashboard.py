#!/usr/bin/env python3
"""
Simple runner script for the EngelGuard Dashboard.

Usage:
    python run_dashboard.py

Or make executable:
    chmod +x run_dashboard.py
    ./run_dashboard.py
"""

import sys
from pathlib import Path

# Add dashboard to path for imports
dashboard_path = Path(__file__).parent / "dashboard"
sys.path.insert(0, str(dashboard_path))

from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
