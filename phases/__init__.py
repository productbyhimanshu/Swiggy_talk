"""
Swiggy Talk — phase-organized source code.

Each subfolder contains only the code for that build phase.
The running API is assembled in phases/assembler.py (entry: backend/main.py).
"""

from phases.assembler import build_app

__all__ = ["build_app"]
