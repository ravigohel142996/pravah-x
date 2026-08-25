"""
FastAPI entrypoint.

Endpoints:
  GET  /catalog              -> agent-readable product catalog (JSON)
  POST /chat                 -> conversational checkout, one turn
  POST /payments/confirm     -> verify a completed Razorpay payment
  GET  /audit/{session_id}   -> full audit trail for one checkout session
  GET  /audit                -> all audit events (for a judge-facing dashboard)
  GET  /                     -> minimal demo frontend (chat + Razorpay Checkout.js)
"""

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import catalog, agent, payments, audit

app = FastAPI(title="Agent-Readable Catalog + Conversational Checkout")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ConfirmPaymentRequest(BaseModel):
    session_id: str
    order_id: str
    payment_id: str
    signature: str


@app.get("/catalog")
def get_catalog():
    """Agent-readable catalog -- what an AI buyer would query."""
    return {"products": [p.model_dump() for p in catalog.get_catalog()]}


@app.post("/chat")
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    result = agent.handle_message(session_id, req.message)
    result["session_id"] = session_id
    return result


@app.post("/payments/confirm")
def confirm_payment(req: ConfirmPaymentRequest):
    is_valid = payments.confirm_payment(
        req.session_id, req.order_id, req.payment_id, req.signature
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail="Payment signature verification failed")
    return {"status": "confirmed"}


@app.get("/audit/{session_id}")
def get_session_audit(session_id: str):
    return {"session_id": session_id, "trail": audit.get_session_trail(session_id)}


@app.get("/audit")
def get_all_audit():
    return {"events": audit.get_all_events()}


@app.get("/", response_class=HTMLResponse)
def demo_page():
    return DEMO_HTML


DEMO_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Agentic Checkout Demo</title>
  <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; }
    #chat { border: 1px solid #ddd; border-radius: 8px; padding: 16px; min-height: 300px; margin-bottom: 12px; }
    .msg { margin: 8px 0; }
    .user { text-align: right; color: #0b5fff; }
    .bot { text-align: left; color: #222; }
    input[type=text] { width: 78%; padding: 8px; }
    button { padding: 8px 14px; }
  </style>
</head>
<body>
  <h2>Agentic Checkout -- Demo</h2>
  <div id="chat"></div>
  <input type="text" id="input" placeholder="e.g. I want a mechanical keyboard" />
  <button onclick="send()">Send</button>

  <script>
    let sessionId = null;
    const chatEl = document.getElementById('chat');

    function addMsg(text, cls) {
      const div = document.createElement('div');
      div.className = 'msg ' + cls;
      div.textContent = text;
      chatEl.appendChild(div);
      chatEl.scrollTop = chatEl.scrollHeight;
    }

    async function send() {
      const input = document.getElementById('input');
      const message = input.value.trim();
      if (!message) return;
      addMsg(message, 'user');
      input.value = '';

      const res = await fetch('/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: sessionId, message})
      });
      const data = await res.json();
      sessionId = data.session_id;
      addMsg(data.reply, 'bot');

      if (data.action === 'checkout_started') {
        openRazorpayCheckout(data);
      }
    }

    function openRazorpayCheckout(data) {
      const options = {
        key: data.razorpay_key_id,
        amount: data.amount_inr * 100,
        currency: 'INR',
        name: 'Agentic Checkout Demo',
        description: 'Test mode purchase',
        order_id: data.order_id,
        handler: async function (response) {
          const confirmRes = await fetch('/payments/confirm', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              session_id: sessionId,
              order_id: response.razorpay_order_id,
              payment_id: response.razorpay_payment_id,
              signature: response.razorpay_signature
            })
          });
          if (confirmRes.ok) {
            addMsg('Payment confirmed! Thank you.', 'bot');
          } else {
            addMsg('Payment could not be verified.', 'bot');
          }
        },
        theme: { color: '#0b5fff' }
      };
      const rzp = new Razorpay(options);
      rzp.open();
    }

    document.getElementById('input').addEventListener('keydown', e => {
      if (e.key === 'Enter') send();
    });
  </script>
</body>
</html>
"""
