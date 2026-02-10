"""Checkpoint state persistence (last_run.json)."""

import json

from .config import STATE_DIR


def load_state() -> dict:
    """Load checkpoint state from last_run.json."""
    state_file = STATE_DIR / "last_run.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def save_state(state: dict):
    """Save checkpoint state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / "last_run.json"
    state_file.write_text(json.dumps(state, indent=2, default=str))
