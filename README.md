# Agentic Checkout System

An AI agent that lets a user buy a product **by chatting**, backed by an agent-readable product catalog and a secure payment API — with every money action logged to a visible audit trail, and payment failure handled gracefully instead of crashing.

> **Requires Python 3.10+** (due to the `list[dict] | None` syntax used in `app/agent.py`).

## Project Structure & Features

- **Agent-readable catalog**: `/catalog` exposes products as structured JSON an AI buyer (ours, or any future one) can query directly.
- **Conversational checkout & multi-turn memory**: `/chat` turns free text ("I want a mechanical keyboard") into a matched product, a confirmation, and a test-mode payment order. It maintains a multi-turn session history so follow-up queries like *"show me something cheaper"* work without repeating the query.
- **Post-checkout upsell suggestions**: After starting a successful checkout, the agent checks an upsell map and suggests companion items (e.g. suggesting an Ergonomic Mouse after a Keyboard purchase) if they are in stock.
- **Every money action explainable, bounded and gated**: `app/audit.py` logs every step (product matched → payment initiated → order created → succeeded/failed) to `audit_log.jsonl` with auto-generated plain-English summaries. View any session's full trail at `/audit/{session_id}`, or all events at `/audit`.
- **Failure handling & safety gates**: If order creation or validation fails (due to bad keys, network issues, double clicks, etc.), the agent does not crash. It catches the error, logs a specific audit event, and replies with a clear, non-technical explanation to the user.

## Architecture

```
User message
     │
     ▼
 /chat (FastAPI) ──► agent.py ──► LLM (Groq or Gemini) decides:
     │                             which product? do they want to buy?
     │
     ├──► catalog.py   (matches / returns product data)
     ├──► payments.py  (creates test order, verifies signature)
     └──► audit.py     (logs every step to audit_log.jsonl)
     │
     ▼
Checkout JS (frontend) ──► /payments/confirm ──► signature verified ──► logged
```

Everything is intentionally simple and readable — the goal is to trace exactly what happened and why.

## Setup

1. **Clone, create virtual environment, and install dependencies:**
   ```bash
   # Create virtual environment
   python -m venv .venv

   # Activate virtual environment:
   # On Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   # On Windows (cmd):
   .venv\Scripts\activate.bat
   # On Unix/macOS:
   source .venv/bin/activate

   # Install production dependencies:
   pip install -r requirements.txt
   ```

2. **Get API keys**: Obtain test keys from your payment provider.

3. **Get an LLM key**: either a [Groq](https://console.groq.com) key (free tier, fast) or a [Gemini](https://aistudio.google.com) key.

4. **Configure:**
   ```bash
   cp .env.example .env
   # fill in RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, and your LLM key
   # set LLM_PROVIDER=groq or LLM_PROVIDER=gemini
   ```

5. **Run:**
   ```bash
   uvicorn main:app --reload
   ```
   Open `http://localhost:8000` — chat with the demo storefront directly in the browser.

6. **Test a real test-mode payment**: use the test card details to complete checkout in the popup.

## Running Tests

To run the automated safety and verification test suite:

1. **Install development requirements:**
   ```bash
   pip install -r requirements-dev.txt
   ```
2. **Execute tests with pytest:**
   ```bash
   pytest tests/ -v
   ```
   This runs 6 safety tests covering the safety-critical paths (out-of-stock guard, duplicate order blocking, signature verification failure handling, LLM call failure recovery, and purchase gates).

## Demoing the failure-handling

You can show the four robust graceful-failure paths live:

1. **Wrong API key (Fallback Triggered)**: Temporarily set `RAZORPAY_KEY_SECRET` in `.env` to an invalid value and restart the server, then try to buy something. The agent will reply with a friendly failure message instead of crashing, and you'll see a `payment_failed` + `fallback_triggered` event pair in `/audit`.
2. **Out of Stock**: Temporarily set `stock=0` on `sku_001` in `app/catalog.py` and try to buy a keyboard. The agent will respond that the item is out of stock and record an `out_of_stock` audit event.
3. **Signature Verification Failure (Tampering)**: Try manually POSTing a confirmation request with an invalid/modified signature:
   ```bash
   curl -X POST http://localhost:8000/payments/confirm \
     -H "Content-Type: application/json" \
     -d '{"session_id":"test-session","order_id":"order_XYZ","payment_id":"pay_123","signature":"invalid_signature"}'
   ```
   The endpoint will return a `400 Bad Request` and log a `signature_verification_failed` event.
4. **Duplicate Order Blocked (Idempotency)**: Try double-clicking checkout or sending multiple checkout confirmation requests for the same session and product. The server rejects the duplicate attempt, raises a `RuntimeError`, and logs a `duplicate_order_blocked` event.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/catalog` | Agent-readable product catalog |
| POST | `/chat` | One turn of the conversational checkout |
| POST | `/payments/confirm` | Verify a completed payment |
| GET | `/audit/{session_id}` | Full audit trail for one checkout |
| GET | `/audit` | All audit events |
| GET | `/audit-dashboard` | Visual timeline dashboard (HTML) |
| GET | `/` | Demo chat UI |

## Project Design Details

- Catalog matching is keyword-based, not embeddings.
- Catalog is in-memory — wire to a real DB for a production feel.
- Only one LLM call per turn (intent parsing).

## Pitch Video Structure

1. **(30s)** State the problem: AI agents need commerce interfaces built for them, not humans.
2. **(2 min)** Live demo: chat → product match → checkout → real test payment completing.
3. **(1 min)** Show the audit trail for that session on the `/audit-dashboard`.
4. **(1 min)** Trigger the failure paths live.
5. **(30s)** Close and architecture diagram.
