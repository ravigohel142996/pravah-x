"""
Razorpay TEST MODE payment handling.

Flow used here: Orders API (server creates an order) -> Checkout.js on
the frontend collects payment against that order -> we verify the
signature server-side. This is Razorpay's standard integration
pattern, just wired for an agent instead of a manual "Buy" button.

IMPORTANT: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET must be TEST keys
(they start with rzp_test_). Never use live keys for a demo/hackathon.
"""

import hmac
import hashlib
import os

import razorpay
from dotenv import load_dotenv

from . import audit

load_dotenv()

_client = None


def get_client() -> razorpay.Client:
    global _client
    if _client is None:
        key_id = os.getenv("RAZORPAY_KEY_ID")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET")
        if not key_id or not key_secret:
            raise RuntimeError(
                "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set. Copy .env.example to .env and fill your TEST keys."
            )
        _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


def create_order(session_id: str, amount_inr: int, product_id: str) -> dict:
    """
    Create a Razorpay order in test mode. Amount must be in paise.
    Logs the attempt to the audit trail before and after, so a
    failure at the API level is captured too, not just failures at
    checkout.
    """
    amount_paise = amount_inr * 100
    audit.log_event(session_id, "payment_initiated", {
        "product_id": product_id,
        "amount_inr": amount_inr,
    })

    try:
        client = get_client()
        order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"receipt_{session_id}",
            "notes": {"product_id": product_id, "session_id": session_id},
        })
        audit.log_event(session_id, "order_created", {
            "order_id": order["id"],
            "amount_paise": amount_paise,
        })
        return order

    except Exception as e:
        # This is the "handle one failure gracefully" moment: we don't
        # crash, we log the failure with full context and return a
        # structured error the agent layer can react to.
        audit.log_event(session_id, "payment_failed", {
            "product_id": product_id,
            "amount_inr": amount_inr,
            "error": str(e),
        })
        raise


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """
    Verify the payment signature Razorpay's Checkout.js returns after
    a successful payment, to confirm it wasn't tampered with client-side.
    """
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    generated_signature = hmac.new(
        key_secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(generated_signature, signature)


def confirm_payment(session_id: str, order_id: str, payment_id: str, signature: str) -> bool:
    """Verify and log the final payment outcome."""
    is_valid = verify_payment_signature(order_id, payment_id, signature)
    audit.log_event(
        session_id,
        "payment_succeeded" if is_valid else "payment_failed",
        {"order_id": order_id, "payment_id": payment_id, "signature_valid": is_valid},
    )
    return is_valid
