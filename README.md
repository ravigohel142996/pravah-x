# Pravah-X — Agentic Checkout System

**Razorpay AI Buildathon · Track 01: AI Growth & Agentic Commerce**

Pravah-X is a conversational checkout agent that lets a user discover and buy products by chatting, powered by an LLM and backed by Razorpay's Orders API in test mode. Every money action is explainable, bounded, and gated: a full audit trail records each step from intent parsing through payment verification, and the agent handles failures gracefully instead of crashing. The core design bar: **no money moves without an auditable reason, and every failure is caught, explained, and logged.**

> **Requires Python 3.10+** (uses `X | Y` union syntax in type hints).

---

## Safety & Trust Design

This is the project's strongest differentiator — trust and auditability are first-class, not bolted on.

### Purchase Gate (LLM proposes, code gates)

The LLM only *suggests* a purchase intent. The code in `agent.py` independently verifies the product exists and is in stock, then logs a **`purchase_gated`** audit event *before* any order is created. The LLM never directly calls the payment API.

### Idempotency / Duplicate Order Blocking

Each `(session_id, product_id)` pair can only create one order. A second attempt is rejected immediately, a **`duplicate_order_blocked`** event is logged, and the user sees a clear message — no double-charges possible.

### 12 Distinct Audit Event Types

Every step of every checkout session is logged to `audit_log.jsonl` with a machine-readable type, a plain-English summary, and full structured details:

| Event Type | Fires When |
|---|---|
| `product_matched` | LLM maps user message to a catalog product |
| `purchase_gated` | Code confirms intent + stock before creating an order |
| `payment_initiated` | Order creation request is about to be sent to Razorpay |
| `order_created` | Razorpay returns a valid order ID |
| `payment_succeeded` | Signature verification passes after checkout |
| `payment_failed` | Razorpay API call fails (network, bad keys, etc.) |
| `signature_verification_failed` | HMAC check fails — possible tampered response |
| `out_of_stock` | Matched product has zero stock |
| `duplicate_order_blocked` | Same session + product already has a pending order |
| `fallback_triggered` | Error caught; user shown a friendly message instead of a crash |
| `llm_error` | LLM API call fails; agent falls back gracefully |
| `upsell_suggested` | Companion product suggested after successful checkout |

View any session's trail at `/audit/{session_id}`, all events at `/audit`, or a visual timeline at `/audit-dashboard`.

---

## Why This Fits Track 01

| Judging Criterion | How Pravah-X Addresses It |
|---|---|
| **Agent-readable catalog** | `/catalog` returns structured JSON any AI buyer can query — no HTML scraping |
| **Agentic checkout flow** | `/chat` drives a full purchase from free-text intent through Razorpay order creation |
| **Every money action explainable** | 12 audit event types, plain-English summaries, visual dashboard |
| **Bounded and gated** | `purchase_gated` event proves the gate fires before any order is created |
| **Failure handling** | 4 distinct failure paths, each caught, logged, and explained to the user |
| **Multi-turn conversation** | Session history (last 5 turns) lets follow-ups like "show me something cheaper" work |
| **Post-checkout upsell** | Companion product suggestions with audit trail — drives growth |

---

## Architecture

```
User message
     │
     ▼
 POST /chat (FastAPI)
     │
     ▼
 agent.py ──► LLM (Groq / Gemini)
     │         "Which product? Do they want to buy?"
     │
     ├──► catalog.py    (structured product lookup)
     │
     ├──► purchase_gated ◄── audit event logged BEFORE order
     │
     ├──► payments.py   (Razorpay Orders API, test mode)
     │         │
     │         └──► order_created / payment_failed ◄── audit
     │
     └──► audit.py      (all events → audit_log.jsonl)
     │
     ▼
Frontend (Checkout.js)
     │
     ▼
 POST /payments/confirm ──► signature verified ──► payment_succeeded ◄── audit
```

Everything is intentionally simple and readable — the goal is to trace exactly what happened and why.

---

## Setup

1. **Clone, create virtual environment, and install dependencies:**
   ```bash
   git clone https://github.com/ravigohel142996/pravah-x.git
   cd pravah-x

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

2. **Get API keys**: Obtain test keys from Razorpay.

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

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Runs 6 automated safety tests covering:

- Out-of-stock guard → friendly reply, correct audit event
- Duplicate order blocking → `RuntimeError` raised, `duplicate_order_blocked` logged
- Signature verification failure → returns `False`, logs `signature_verification_failed` (not generic `payment_failed`)
- LLM call failure → graceful reply, `llm_error` logged, no crash
- Purchase gate ordering → `purchase_gated` appears in audit trail strictly *before* `order_created`

No real API keys required — all external calls are monkeypatched.

---

## Demoing the Failure-Handling

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

---

## API Reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/catalog` | Agent-readable product catalog |
| `POST` | `/chat` | One turn of the conversational checkout |
| `POST` | `/payments/confirm` | Verify a completed payment |
| `GET` | `/audit/{session_id}` | Full audit trail for one checkout |
| `GET` | `/audit` | All audit events |
| `GET` | `/audit-dashboard` | Visual timeline dashboard (HTML) |
| `GET` | `/` | Demo chat UI |

---

## Deploy on Render

This repository includes a `render.yaml` blueprint for a Render Web Service.

1. Push this repository to GitHub.
2. In Render, create a new Blueprint and select this repository.
3. Render will use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set the required environment variables in Render:
   - `RAZORPAY_KEY_ID`
   - `RAZORPAY_KEY_SECRET`
   - `LLM_PROVIDER` (`groq` or `gemini`)
   - `GROQ_API_KEY` (required when `LLM_PROVIDER=groq`)
   - `GEMINI_API_KEY` (required when `LLM_PROVIDER=gemini`)

---

## Project Design Details

- Catalog matching is keyword-based, not embeddings.
- Catalog is in-memory — wire to a real DB for a production feel.
- Only one LLM call per turn (intent parsing).

---

## Pitch Video Structure

1. **(30s)** State the problem: AI agents need commerce interfaces built for them, not humans.
2. **(2 min)** Live demo: chat → product match → checkout → real test payment completing.
3. **(1 min)** Show the audit trail for that session on the `/audit-dashboard`.
4. **(1 min)** Trigger the failure paths live.
5. **(30s)** Close and architecture diagram.
