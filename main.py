"""
FastAPI entrypoint.

Endpoints:
  GET  /catalog              -> agent-readable product catalog (JSON)
  POST /chat                 -> conversational checkout, one turn
  POST /payments/confirm     -> verify a completed Razorpay payment
  GET  /audit/{session_id}   -> full audit trail for one checkout session
  GET  /audit                -> all audit events (for a judge-facing dashboard)
  GET  /audit-dashboard      -> visual timeline dashboard (HTML, judge-facing)
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


@app.get("/audit-dashboard", response_class=HTMLResponse)
def audit_dashboard_page():
    """Visual audit trail timeline -- pick a session, see every step in plain English."""
    return AUDIT_DASHBOARD_HTML


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


AUDIT_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Audit Trail Dashboard — Pravah-X</title>
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
    }
    .topbar {
      background: #1e293b;
      border-bottom: 1px solid #334155;
      padding: 14px 24px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .topbar h1 { font-size: 1rem; font-weight: 700; color: #f1f5f9; }
    .badge {
      font-size: 0.65rem; font-weight: 700;
      letter-spacing: 0.1em; text-transform: uppercase;
      background: #3b82f6; color: #fff;
      padding: 2px 8px; border-radius: 999px;
    }
    .topbar-link {
      margin-left: auto; font-size: 0.8rem;
      color: #64748b; text-decoration: none;
    }
    .topbar-link:hover { color: #94a3b8; }
    .container { max-width: 760px; margin: 0 auto; padding: 28px 16px; }
    .session-row {
      display: flex; align-items: center; gap: 10px;
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 14px 16px;
      margin-bottom: 28px;
    }
    .session-row label {
      font-size: 0.75rem; color: #94a3b8;
      white-space: nowrap; font-weight: 700;
      letter-spacing: 0.06em; text-transform: uppercase;
    }
    .session-row select {
      flex: 1;
      background: #0f172a;
      border: 1px solid #475569;
      border-radius: 6px;
      color: #e2e8f0;
      padding: 7px 10px;
      font-size: 0.85rem; font-family: 'Courier New', monospace;
      outline: none; cursor: pointer;
    }
    .session-row select:focus { border-color: #3b82f6; }
    .cnt { font-size: 0.75rem; color: #64748b; white-space: nowrap; }
    #status {
      text-align: center; color: #475569;
      font-size: 0.9rem; padding: 60px 0;
    }
    /* Timeline */
    .tl { position: relative; padding-left: 36px; }
    .tl::before {
      content: ''; position: absolute;
      left: 11px; top: 24px; bottom: 24px;
      width: 2px;
      background: linear-gradient(to bottom, #3b82f6 0%, #1e293b 100%);
    }
    .ev {
      position: relative; margin-bottom: 16px;
      animation: slideIn 0.22s ease both;
    }
    @keyframes slideIn {
      from { opacity: 0; transform: translateX(-8px); }
      to   { opacity: 1; transform: translateX(0); }
    }
    .ev-dot {
      position: absolute; left: -30px; top: 14px;
      width: 22px; height: 22px; border-radius: 50%;
      border: 2px solid #0f172a;
      display: flex; align-items: center; justify-content: center;
      font-size: 11px; line-height: 1; z-index: 1;
    }
    .ev-card {
      background: #1e293b;
      border: 1px solid #2d3f55;
      border-radius: 10px; overflow: hidden;
      transition: border-color 0.15s;
    }
    .ev-card:hover { border-color: #475569; }
    .ev-main { padding: 12px 14px; display: flex; flex-direction: column; gap: 5px; }
    .ev-row1 { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .ev-tag {
      font-size: 0.65rem; font-weight: 700;
      letter-spacing: 0.08em; text-transform: uppercase;
      padding: 2px 8px; border-radius: 4px;
    }
    .ev-time { font-size: 0.72rem; color: #64748b; font-variant-numeric: tabular-nums; }
    .ev-summary { font-size: 0.875rem; color: #e2e8f0; font-weight: 500; line-height: 1.45; }
    details.ev-raw { border-top: 1px solid #334155; }
    details.ev-raw summary {
      padding: 6px 14px; font-size: 0.72rem; color: #64748b;
      cursor: pointer; list-style: none; user-select: none;
    }
    details.ev-raw summary::-webkit-details-marker { display: none; }
    details.ev-raw summary::before { content: '\25B6\00A0 Raw JSON'; }
    details.ev-raw[open] summary::before { content: '\25BC\00A0 Raw JSON'; }
    details.ev-raw pre {
      background: #0d1a2d; color: #7dd3fc;
      font-size: 0.75rem; padding: 10px 14px;
      overflow-x: auto; line-height: 1.6;
    }
    /* Per-category colours (dot / tag background / left border) */
    .c-success .ev-dot  { background: #22c55e; }
    .c-success .ev-tag  { background: #14532d; color: #4ade80; }
    .c-success .ev-card { border-left: 3px solid #22c55e; }
    .c-failure .ev-dot  { background: #ef4444; }
    .c-failure .ev-tag  { background: #450a0a; color: #f87171; }
    .c-failure .ev-card { border-left: 3px solid #ef4444; }
    .c-info .ev-dot     { background: #3b82f6; }
    .c-info .ev-tag     { background: #1e3a5f; color: #60a5fa; }
    .c-info .ev-card    { border-left: 3px solid #3b82f6; }
    .c-warning .ev-dot  { background: #f97316; }
    .c-warning .ev-tag  { background: #431407; color: #fb923c; }
    .c-warning .ev-card { border-left: 3px solid #f97316; }
    .c-blocked .ev-dot  { background: #6b7280; }
    .c-blocked .ev-tag  { background: #1c1917; color: #9ca3af; }
    .c-blocked .ev-card { border-left: 3px solid #6b7280; }
    .c-upsell .ev-dot   { background: #eab308; }
    .c-upsell .ev-tag   { background: #422006; color: #fbbf24; }
    .c-upsell .ev-card  { border-left: 3px solid #eab308; }
    .c-gate .ev-dot     { background: #a855f7; }
    .c-gate .ev-tag     { background: #2e1065; color: #c084fc; }
    .c-gate .ev-card    { border-left: 3px solid #a855f7; }
  </style>
</head>
<body>
  <header class="topbar">
    <span style="font-size:1.25rem">&#128203;</span>
    <h1>Audit Trail Dashboard</h1>
    <span class="badge">Pravah&#8209;X</span>
    <a class="topbar-link" href="/">&#8592; Back to Demo</a>
  </header>

  <main class="container">
    <div class="session-row">
      <label for="sel">Session</label>
      <select id="sel"><option value="">&#8212; loading sessions… &#8212;</option></select>
      <span id="cnt" class="cnt"></span>
    </div>
    <div id="status">Select a session above to view its audit timeline.</div>
    <div id="tl" class="tl" style="display:none"></div>
  </main>

  <script>
    const META = {
      product_matched:               { cat:'info',    icon:'&#128269;', label:'product_matched'     },
      payment_initiated:             { cat:'info',    icon:'&#128179;', label:'payment_initiated'    },
      purchase_gated:                { cat:'gate',    icon:'&#128274;', label:'purchase_gated'       },
      order_created:                 { cat:'info',    icon:'&#128230;', label:'order_created'        },
      payment_succeeded:             { cat:'success', icon:'&#9989;',   label:'payment_succeeded'    },
      payment_failed:                { cat:'failure', icon:'&#10060;',  label:'payment_failed'       },
      out_of_stock:                  { cat:'failure', icon:'&#128683;', label:'out_of_stock'         },
      fallback_triggered:            { cat:'warning', icon:'&#9888;',   label:'fallback_triggered'   },
      duplicate_order_blocked:       { cat:'blocked', icon:'&#128721;', label:'duplicate_blocked'   },
      signature_verification_failed: { cat:'failure', icon:'&#128272;', label:'sig_verify_failed'   },
      llm_error:                     { cat:'failure', icon:'&#129302;', label:'llm_error'            },
      upsell_suggested:              { cat:'upsell',  icon:'&#128161;', label:'upsell_suggested'     },
    };
    function meta(t) { return META[t] || { cat:'info', icon:'&#128203;', label:t }; }
    function fmtTime(ts) {
      return new Date(ts * 1000).toLocaleTimeString('en-IN', {
        hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:true
      });
    }
    async function loadSessions() {
      try {
        const r = await fetch('/audit');
        const data = await r.json();
        const seen = new Set(), ids = [];
        for (const e of (data.events || [])) {
          if (!seen.has(e.session_id)) { seen.add(e.session_id); ids.push(e.session_id); }
        }
        const sel = document.getElementById('sel');
        const cur = sel.value;
        sel.innerHTML = '<option value="">&#8212; select a session &#8212;</option>' +
          ids.map(id =>
            '<option value="' + id + '"' + (id===cur?' selected':'') + '>' +
            id.slice(0,8) + '\u2026</option>'
          ).join('');
        if (!cur) document.getElementById('status').textContent =
          ids.length
            ? 'Select a session above to view its audit timeline.'
            : 'No sessions yet \u2014 start a chat to generate audit events.';
      } catch(e) { /* server not ready yet */ }
    }
    async function loadSession(sid) {
      const statusEl = document.getElementById('status');
      const tlEl     = document.getElementById('tl');
      const cntEl    = document.getElementById('cnt');
      if (!sid) {
        statusEl.style.display='block'; tlEl.style.display='none';
        cntEl.textContent=''; return;
      }
      statusEl.textContent='Loading\u2026'; statusEl.style.display='block';
      tlEl.style.display='none';
      const r = await fetch('/audit/' + sid);
      const data = await r.json();
      const trail = data.trail || [];
      if (!trail.length) { statusEl.textContent='No events for this session.'; return; }
      cntEl.textContent = trail.length + ' event' + (trail.length===1?'':'s');
      tlEl.innerHTML = trail.map(renderEv).join('');
      statusEl.style.display='none'; tlEl.style.display='block';
    }
    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
    function renderEv(ev) {
      const m = meta(ev.event_type);
      const details = esc(JSON.stringify(ev.details, null, 2));
      return '<div class="ev c-' + m.cat + '">' +
        '<div class="ev-dot">' + m.icon + '</div>' +
        '<div class="ev-card">' +
          '<div class="ev-main">' +
            '<div class="ev-row1">' +
              '<span class="ev-tag">' + m.label + '</span>' +
              '<span class="ev-time">' + fmtTime(ev.timestamp) + '</span>' +
            '</div>' +
            '<div class="ev-summary">' + esc(ev.summary || ev.event_type) + '</div>' +
          '</div>' +
          '<details class="ev-raw"><summary></summary>' +
          '<pre>' + details + '</pre></details>' +
        '</div>' +
      '</div>';
    }
    document.getElementById('sel').addEventListener('change', e => loadSession(e.target.value));
    loadSessions();
    setInterval(loadSessions, 5000);
  </script>
</body>
</html>
"""
