"""Shared configuration state for tool handlers."""

import os

SOURCEPILOT_URL: str = os.getenv("SOURCEPILOT_URL", "http://localhost:9000")
