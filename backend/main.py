"""API entrypoint — assembles all completed phases."""

from phases.assembler import build_app

app = build_app()
