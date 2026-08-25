"""
Audit trail.

The track brief explicitly says: "Every money action explainable,
bounded and gated. Show the audit trail." This module is that trail --
every step of a checkout (product matched, price shown, payment
attempted, payment result, failure handling) gets logged here as a
structured event, and can be replayed / displayed to judges.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any

AUDIT_LOG_PATH = Path(__file__).parent.parent / "audit_log.jsonl"


def log_event(session_id: str, event_type: str, details: dict[str, Any]) -> dict:
    """
    Append one structured audit event. Using JSON Lines so it's trivial
    to tail, grep, or load into a dataframe for the pitch video.
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "timestamp": time.time(),
        "event_type": event_type,   # e.g. "product_matched", "payment_initiated", "payment_failed", "payment_succeeded", "fallback_triggered"
        "details": details,
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")
    return event


def get_session_trail(session_id: str) -> list[dict]:
    """Return the full ordered audit trail for one checkout session."""
    if not AUDIT_LOG_PATH.exists():
        return []
    trail = []
    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            event = json.loads(line)
            if event["session_id"] == session_id:
                trail.append(event)
    return trail


def get_all_events() -> list[dict]:
    """Return every audit event ever logged -- useful for a judge-facing dashboard."""
    if not AUDIT_LOG_PATH.exists():
        return []
    with open(AUDIT_LOG_PATH) as f:
        return [json.loads(line) for line in f]
