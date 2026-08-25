"""
Audit trail.

The track brief explicitly says: "Every money action explainable,
bounded and gated. Show the audit trail." This module is that trail --
every step of a checkout (product matched, price shown, payment
attempted, payment result, failure handling) gets logged here as a
structured event, and can be replayed / displayed to judges.

Each event now includes a plain-English 'summary' field so that
`cat audit_log.jsonl` is fully readable without touching code.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any

# audit_log.jsonl lives at the repo root regardless of where this file is.
AUDIT_LOG_PATH = Path(__file__).parent.parent / "audit_log.jsonl"


def _auto_summary(event_type: str, details: dict) -> str:
    """
    Generate a plain-English one-liner for any known event type.
    Called automatically by log_event() when no explicit summary is passed.
    """
    if event_type == "product_matched":
        pid = details.get("product_id", "unknown")
        return f"Matched product '{pid}' to user query."

    elif event_type == "payment_initiated":
        amt = details.get("amount_inr", "?")
        pid = details.get("product_id", "?")
        return f"Payment initiated for \u20b9{amt} (product {pid})."

    elif event_type == "order_created":
        oid = details.get("order_id", "?")
        amt_paise = details.get("amount_paise", 0)
        rupees = amt_paise // 100 if isinstance(amt_paise, int) else "?"
        return f"Payment gateway order {oid} created for \u20b9{rupees}."

    elif event_type == "payment_succeeded":
        pid = details.get("payment_id", "?")
        return f"Payment {pid} confirmed \u2014 signature valid."

    elif event_type == "payment_failed":
        err = details.get("error", "unknown error")
        return f"Payment failed: {err}."

    elif event_type == "fallback_triggered":
        err = details.get("error", "unknown error")
        return (
            f"Fallback activated \u2014 user shown a plain-English error message. ({err})"
        )

    elif event_type == "out_of_stock":
        pid = details.get("product_id", "?")
        stock = details.get("stock", 0)
        return f"Product {pid} is out of stock ({stock} units available)."

    elif event_type == "duplicate_order_blocked":
        pid = details.get("product_id", "?")
        return f"Duplicate order attempt blocked for product {pid} in this session."

    elif event_type == "signature_verification_failed":
        oid = details.get("order_id", "?")
        return (
            f"Signature check failed for order {oid} \u2014 possible tampered response."
        )

    elif event_type == "purchase_gated":
        pid = details.get("product_id", "?")
        return (
            f"Purchase gate passed: LLM confirmed intent for product {pid}. "
            "Proceeding to order creation."
        )

    elif event_type == "upsell_suggested":
        from_pid = details.get("purchased_product_id", "?")
        to_name = details.get("upsell_product_name", "?")
        to_pid = details.get("upsell_product_id", "?")
        return f"Upsell: suggested '{to_name}' ({to_pid}) after purchase of {from_pid}."

    elif event_type == "llm_error":
        err = details.get("error", "unknown error")
        return f"LLM call failed \u2014 fallback reply shown to user. ({err})"

    else:
        return f"Event: {event_type}."


def log_event(
    session_id: str,
    event_type: str,
    details: dict[str, Any],
    summary: str = "",
) -> dict:
    """
    Append one structured audit event to audit_log.jsonl.

    Args:
        session_id:  The checkout session this event belongs to.
        event_type:  Machine-readable label (e.g. 'payment_succeeded').
        details:     Arbitrary key/value context for this event.
        summary:     Optional human-readable one-liner. Auto-generated from
                     event_type + details if omitted, so callers don't have to
                     think about it -- but they can override it.

    Returns the event dict that was written (useful in tests).
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "timestamp": time.time(),
        "event_type": event_type,
        "summary": summary or _auto_summary(event_type, details),
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
