# Agentic Checkout System

An AI agent that lets a user buy a product **by chatting**, backed by an
agent-readable product catalog and a secure payment API — with every
money action logged to a visible audit trail, and payment failure
handled gracefully instead of crashing.

## Project Structure & Features

- **Agent-readable catalog**: `/catalog` exposes products as structured
  JSON an AI buyer (ours, or any future one) can query directly.
- **Conversational checkout**: `/chat` turns free text ("I want a
  mechanical keyboard") into a matched product, a confirmation, and a
  test-mode payment order.
- **Every money action explainable, bounded and gated**: `app/audit.py`
  logs every step (product matched → payment initiated → order created
  → succeeded/failed) to `audit_log.jsonl`. View any session's full
  trail at `/audit/{session_id}`, or all events at `/audit`.
- **Failure handling**: if order creation fails (bad keys, network issue, etc.),
  the agent doesn't crash — it logs a `fallback_triggered` event and replies
  with a clear, non-technical message to the user.

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

1. **Clone and install:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Get API keys**: Obtain test keys from your payment provider.

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

6. **Test a real test-mode payment**: use the test card details to complete
   checkout in the popup.

## Demoing the failure-handling

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
| POST | `/payments/confirm` | Verify a completed payment |
| GET | `/audit/{session_id}` | Full audit trail for one checkout |
| GET | `/audit` | All audit events |
| GET | `/` | Demo chat UI |

## Project Design Details

- Catalog matching is keyword-based, not embeddings.
- Catalog is in-memory — wire to a real DB for a production feel.
- Only one LLM call per turn (intent parsing).

## Pitch Video Structure

1. **(30s)** State the problem: AI agents need commerce interfaces
   built for them, not humans.
2. **(2 min)** Live demo: chat → product match → checkout → real test
   payment completing.
3. **(1 min)** Show the audit trail for that session.
4. **(1 min)** Trigger the failure path live.
5. **(30s)** Close and architecture diagram.
