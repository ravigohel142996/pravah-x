# Agentic Checkout — Razorpay AI Buildathon (Track 01: AI Growth & Agentic Commerce)

An AI agent that lets a user buy a product **by chatting**, backed by an
agent-readable product catalog and Razorpay's payments API — with every
money action logged to a visible audit trail, and one payment failure
handled gracefully instead of crashing.

## Why this fits Track 01

- **Agent-readable catalog**: `/catalog` exposes products as structured
  JSON an AI buyer (ours, or any future one) can query directly —
  no HTML scraping needed.
- **Conversational checkout**: `/chat` turns free text ("I want a
  mechanical keyboard") into a matched product, a confirmation, and a
  real Razorpay test-mode order.
- **Every money action explainable, bounded and gated**: `app/audit.py`
  logs every step (product matched → payment initiated → order created
  → succeeded/failed) to `audit_log.jsonl`. View any session's full
  trail at `/audit/{session_id}`, or all events at `/audit`.
- **One failure handled gracefully**: if order creation fails (bad
  keys, network issue, etc.), the agent doesn't crash — it logs a
  `fallback_triggered` event and replies with a clear, non-technical
  message to the user (see `agent.py::handle_message`, the `except`
  branch).

## Architecture

```
User message
     │
     ▼
 /chat (FastAPI) ──► agent.py ──► LLM (Groq or Gemini) decides:
     │                             which product? do they want to buy?
     │
     ├──► catalog.py   (matches / returns product data)
     ├──► payments.py  (creates Razorpay test order, verifies signature)
     └──► audit.py     (logs every step to audit_log.jsonl)
     │
     ▼
Razorpay Checkout.js (frontend) ──► /payments/confirm ──► signature verified ──► logged
```

Everything is intentionally simple and readable — the goal is a judge
being able to trace exactly what happened and why, not a maximally
clever implementation.

## Setup

1. **Clone and install:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Get Razorpay TEST keys**: Razorpay Dashboard → Settings → API Keys
   → generate **Test Mode** keys (they start with `rzp_test_`).

3. **Get an LLM key**: either a [Groq](https://console.groq.com) key
   (free tier, fast) or a [Gemini](https://aistudio.google.com) key.

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
   Open `http://localhost:8000` — chat with the demo storefront directly
   in the browser.

6. **Test a real test-mode payment**: use Razorpay's test card
   `4111 1111 1111 1111`, any future expiry, any CVV, to complete
   checkout in the popup.

## Demoing the failure-handling for judges

To show the graceful-failure path live: temporarily set
`RAZORPAY_KEY_SECRET` in `.env` to an invalid value and restart the
server, then try to buy something. The agent will reply with a plain,
non-technical failure message instead of crashing, and you'll see a
`payment_failed` + `fallback_triggered` pair in `/audit`. Put the
correct key back afterward.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/catalog` | Agent-readable product catalog |
| POST | `/chat` | One turn of the conversational checkout |
| POST | `/payments/confirm` | Verify a completed Razorpay payment |
| GET | `/audit/{session_id}` | Full audit trail for one checkout |
| GET | `/audit` | All audit events (judge dashboard) |
| GET | `/` | Demo chat UI |

## What's deliberately simple (and what to extend if you have time)

- Catalog matching is keyword-based, not embeddings — swap in a vector
  search if you want to show more sophistication.
- Catalog is in-memory — wire to a real DB for a "production" feel.
- Only one LLM call per turn (intent parsing) — you could add a second
  pass for richer upsell/cross-sell logic per the track's example
  directions.

## 5-minute pitch video structure

1. **(30s)** State the problem: AI agents need commerce interfaces
   built for them, not humans — catalogs and checkout flows built for
   web pages don't work for AI buyers.
2. **(2 min)** Live demo: chat → product match → checkout → real test
   payment completing.
3. **(1 min)** Show the audit trail for that session — every money
   action, explainable.
4. **(1 min)** Trigger the failure path live, show the graceful
   response and the corresponding audit events.
5. **(30s)** Close: architecture diagram, what you'd build next with
   more time (real catalog DB, embeddings-based matching, multi-item
   carts).
