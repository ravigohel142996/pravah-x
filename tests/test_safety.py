"""
tests/test_safety.py
--------------------
Item 2.5c: Six pytest tests covering the safety-critical paths.

No real API keys are needed — all external calls are monkeypatched.
Run with:  pytest tests/ -v
"""

import json
import os
import sys
import types
import importlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to build a fake razorpay module so payments.py can import without
# the package installed AND without real credentials.
# ---------------------------------------------------------------------------

def _make_fake_razorpay_module():
    """Return a minimal fake `razorpay` module accepted by payments.py."""
    mod = types.ModuleType("razorpay")

    class FakeOrder:
        def create(self, data):
            return {"id": "order_FAKE123", "amount": data["amount"]}

    class FakeClient:
        def __init__(self, auth):
            self.order = FakeOrder()

    mod.Client = FakeClient
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _inject_fake_razorpay(monkeypatch):
    """Ensure `razorpay` is available as a fake for every test."""
    fake = _make_fake_razorpay_module()
    monkeypatch.setitem(sys.modules, "razorpay", fake)


@pytest.fixture()
def tmp_audit_log(monkeypatch, tmp_path):
    """Redirect audit log writes to a temp file; return the path."""
    log_file = tmp_path / "audit_log.jsonl"
    # Reload audit with the patched path BEFORE importing payments/agent
    import app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_PATH", log_file)
    return log_file


def _read_events(log_file: Path) -> list[dict]:
    if not log_file.exists():
        return []
    return [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]


def _event_types(log_file: Path) -> list[str]:
    return [e["event_type"] for e in _read_events(log_file)]


# ---------------------------------------------------------------------------
# Shared setup: reset module-level state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_payments_state():
    """Clear the _pending_orders set before each test."""
    import app.payments as payments_mod
    payments_mod._pending_orders.clear()
    yield
    payments_mod._pending_orders.clear()


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Provide dummy env vars so payments.get_client() doesn't raise."""
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "dummy_secret")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "dummy_groq_key")
    # Reset cached razorpay client so the fake one is used
    import app.payments as payments_mod
    payments_mod._client = None


# ---------------------------------------------------------------------------
# Test 1: out-of-stock → friendly reply, action == "out_of_stock"
# ---------------------------------------------------------------------------

def test_out_of_stock_returns_friendly_reply(tmp_audit_log, monkeypatch):
    """stock=0 on a matched product → handle_message returns action='out_of_stock', no crash."""
    import app.catalog as catalog_mod
    import app.agent as agent_mod

    # Patch _parse_intent to return a known product that wants_to_buy=True
    monkeypatch.setattr(
        agent_mod, "_parse_intent",
        lambda msg, history=None: {"product_id": "sku_001", "wants_to_buy": True, "reply": ""},
    )
    # Set stock to 0
    original_stock = catalog_mod.CATALOG["sku_001"].stock
    catalog_mod.CATALOG["sku_001"] = catalog_mod.CATALOG["sku_001"].model_copy(update={"stock": 0})

    try:
        result = agent_mod.handle_message("sess_oos_1", "buy a keyboard")
    finally:
        catalog_mod.CATALOG["sku_001"] = catalog_mod.CATALOG["sku_001"].model_copy(update={"stock": original_stock})

    assert result["action"] == "out_of_stock"
    assert "out of stock" in result["reply"].lower()


# ---------------------------------------------------------------------------
# Test 2: out-of-stock → writes audit event
# ---------------------------------------------------------------------------

def test_out_of_stock_writes_audit_event(tmp_audit_log, monkeypatch):
    """stock=0 → 'out_of_stock' event is written to the audit log."""
    import app.catalog as catalog_mod
    import app.agent as agent_mod

    monkeypatch.setattr(
        agent_mod, "_parse_intent",
        lambda msg, history=None: {"product_id": "sku_001", "wants_to_buy": True, "reply": ""},
    )
    original_stock = catalog_mod.CATALOG["sku_001"].stock
    catalog_mod.CATALOG["sku_001"] = catalog_mod.CATALOG["sku_001"].model_copy(update={"stock": 0})

    try:
        agent_mod.handle_message("sess_oos_2", "buy a keyboard")
    finally:
        catalog_mod.CATALOG["sku_001"] = catalog_mod.CATALOG["sku_001"].model_copy(update={"stock": original_stock})

    assert "out_of_stock" in _event_types(tmp_audit_log)


# ---------------------------------------------------------------------------
# Test 3: duplicate order → second call raises, logs duplicate_order_blocked
# ---------------------------------------------------------------------------

def test_duplicate_order_is_blocked(tmp_audit_log):
    """Calling create_order twice for the same session/product raises RuntimeError
    and logs a 'duplicate_order_blocked' audit event on the second call."""
    import app.payments as payments_mod

    # First call should succeed (fake razorpay returns a dict)
    payments_mod.create_order("sess_dup", 3499, "sku_001")

    # Second call for the same session+product must raise
    with pytest.raises(RuntimeError, match="Order already in progress"):
        payments_mod.create_order("sess_dup", 3499, "sku_001")

    assert "duplicate_order_blocked" in _event_types(tmp_audit_log)


# ---------------------------------------------------------------------------
# Test 4: bad signature → confirm_payment returns False, logs
#          signature_verification_failed
# ---------------------------------------------------------------------------

def test_signature_failure_returns_false(tmp_audit_log, monkeypatch):
    """A tampered/wrong signature → confirm_payment returns False and logs
    'signature_verification_failed' (NOT a generic 'payment_failed')."""
    import app.payments as payments_mod

    result = payments_mod.confirm_payment(
        "sess_sig",
        order_id="order_ABC",
        payment_id="pay_XYZ",
        signature="totally_wrong_signature",
    )

    assert result is False
    event_types = _event_types(tmp_audit_log)
    assert "signature_verification_failed" in event_types
    # Must NOT be logged as the generic payment_failed
    assert "payment_failed" not in event_types


# ---------------------------------------------------------------------------
# Test 5: LLM error → graceful reply, action == "error", no crash
# ---------------------------------------------------------------------------

def test_llm_error_returns_graceful_reply(tmp_audit_log, monkeypatch):
    """If _parse_intent raises, handle_message catches it, logs 'llm_error',
    and returns a user-friendly reply without crashing."""
    import app.agent as agent_mod

    monkeypatch.setattr(
        agent_mod, "_parse_intent",
        lambda msg, history=None: (_ for _ in ()).throw(RuntimeError("LLM API timeout")),
    )

    result = agent_mod.handle_message("sess_llm_err", "anything")

    assert result["action"] == "error"
    assert "trouble" in result["reply"].lower()
    assert "llm_error" in _event_types(tmp_audit_log)


# ---------------------------------------------------------------------------
# Test 6: happy path → purchase_gated event appears BEFORE order_created
# ---------------------------------------------------------------------------

def test_purchase_gate_event_is_logged(tmp_audit_log, monkeypatch):
    """On a successful buy, 'purchase_gated' must appear in the audit trail
    strictly before 'order_created' — proving the gate fires pre-execution."""
    import app.agent as agent_mod
    import app.catalog as catalog_mod

    # Ensure sku_001 is in stock
    catalog_mod.CATALOG["sku_001"] = catalog_mod.CATALOG["sku_001"].model_copy(update={"stock": 12})

    monkeypatch.setattr(
        agent_mod, "_parse_intent",
        lambda msg, history=None: {"product_id": "sku_001", "wants_to_buy": True, "reply": "Sure!"},
    )

    result = agent_mod.handle_message("sess_gate", "buy a keyboard")

    assert result["action"] == "checkout_started"

    event_types = _event_types(tmp_audit_log)
    assert "purchase_gated" in event_types
    assert "order_created" in event_types

    # Order matters: purchase_gated index must be < order_created index
    gate_idx = event_types.index("purchase_gated")
    created_idx = event_types.index("order_created")
    assert gate_idx < created_idx, (
        f"Expected purchase_gated (idx {gate_idx}) before order_created (idx {created_idx})"
    )
