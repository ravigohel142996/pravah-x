"""
Conversational checkout agent.

Takes a free-text user message, figures out what product they want
(using the catalog + an LLM for intent parsing), and drives the
checkout via payments.py. Every step writes to the audit trail.

Swap LLM_PROVIDER in .env between "groq" and "gemini" -- both are
wired here so you can demo whichever key you have first.

Item 3a: SESSIONS dict stores per-session conversation history (last 5
turns). Both LLM callers thread that history into the messages array so
follow-up queries like "show me something cheaper" or "actually make it 2"
resolve correctly without the user re-stating their full request.

Item 3b: UPSELL_MAP drives a post-checkout suggestion. After a successful
checkout_started, if a mapped companion product exists and is in stock, we
append a short suggestion to the reply and log an upsell_suggested event.
"""

import os
import json
from collections import deque
from dotenv import load_dotenv

from . import catalog, payments, audit

load_dotenv()

# ---------------------------------------------------------------------------
# Item 3a — per-session conversation history
# ---------------------------------------------------------------------------

# Maps session_id → deque of message dicts {"role": "user"|"assistant", "content": str}
# Capped at MAX_HISTORY_TURNS to keep the prompt size bounded.
SESSIONS: dict[str, deque] = {}
MAX_HISTORY_TURNS = 5  # keep the last 5 full exchanges (10 messages)


def _get_history(session_id: str) -> list[dict]:
    """Return the current history list for a session (may be empty)."""
    return list(SESSIONS.get(session_id, []))


def _append_history(session_id: str, role: str, content: str) -> None:
    """Append one message to the session history, respecting the cap."""
    if session_id not in SESSIONS:
        SESSIONS[session_id] = deque(maxlen=MAX_HISTORY_TURNS * 2)
    SESSIONS[session_id].append({"role": role, "content": content})


# ---------------------------------------------------------------------------
# Item 3b — upsell map
# ---------------------------------------------------------------------------

# Maps purchased product_id → product_id to suggest immediately after checkout.
# Intentionally bidirectional: keyboard buyer gets mouse suggestion and vice-versa.
UPSELL_MAP: dict[str, str] = {
    "sku_001": "sku_002",   # Keyboard → Ergonomic Mouse
    "sku_002": "sku_001",   # Mouse → Wireless Keyboard
    "sku_003": "sku_004",   # Monitor → Laptop Stand
    "sku_004": "sku_003",   # Stand → Monitor
}


def _build_upsell_suffix(purchased_product_id: str, session_id: str) -> str:
    """
    If a companion product is mapped and in stock, return a suggestion sentence
    and log the upsell_suggested audit event. Returns "" if no upsell applies.
    """
    upsell_id = UPSELL_MAP.get(purchased_product_id)
    if not upsell_id:
        return ""
    upsell_product = catalog.get_product(upsell_id)
    if not upsell_product or upsell_product.stock <= 0:
        return ""

    audit.log_event(session_id, "upsell_suggested", {
        "purchased_product_id": purchased_product_id,
        "upsell_product_id": upsell_product.id,
        "upsell_product_name": upsell_product.name,
    })
    return (
        f" By the way, customers who bought this often pair it with the "
        f"{upsell_product.name} (₹{upsell_product.price_inr}) — want to add it?"
    )


# ---------------------------------------------------------------------------
# System prompt — updated to mention conversation context (Item 3a)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a shopping assistant for an online store.
You have access to the conversation history AND a product catalog.
Use the history to resolve follow-up queries like "show me something cheaper",
"the second one", or "actually make it 2" without the user repeating themselves.

Given the latest user message, decide:
1. Which single product (if any) the user most likely wants, by id.
2. Whether they've confirmed they want to buy it (vs just browsing/asking).

Respond ONLY with JSON in this exact shape, no other text:
{"product_id": "<id or null>", "wants_to_buy": true or false, "reply": "<short natural reply to the user>"}
"""


# ---------------------------------------------------------------------------
# LLM callers — both now accept and thread history (Item 3a)
# ---------------------------------------------------------------------------

def _call_groq(user_message: str, catalog_text: str, history: list[dict]) -> dict:
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + f"\n\nCatalog:\n{catalog_text}"},
        *history,
        {"role": "user", "content": user_message},
    ]

    custom_model = os.getenv("GROQ_MODEL")
    candidate_models = [m for m in [custom_model, "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "qwen/qwen3.6-27b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"] if m]

    last_error = None
    for model_name in candidate_models:
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            last_error = e
            continue

    if last_error:
        raise last_error



def _call_gemini(user_message: str, catalog_text: str, history: list[dict]) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT + f"\n\nCatalog:\n{catalog_text}",
    )
    # Gemini uses "model" instead of "assistant" for its role label
    gemini_history = [
        {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
        for m in history
    ]
    chat = model.start_chat(history=gemini_history)
    response = chat.send_message(
        user_message,
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def _parse_intent(user_message: str, history: list[dict] | None = None) -> dict:
    catalog_text = "\n".join(
        f"- id={p.id} | {p.name} | ₹{p.price_inr} | {p.description}"
        for p in catalog.get_catalog()
    )
    history = history or []
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "gemini":
        return _call_gemini(user_message, catalog_text, history)
    return _call_groq(user_message, catalog_text, history)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def handle_message(session_id: str, user_message: str) -> dict:
    """
    One turn of the conversation.
    Returns a dict the API layer sends straight back to the frontend.
    """
    history = _get_history(session_id)

    try:
        intent = _parse_intent(user_message, history)
    except Exception as e:
        audit.log_event(session_id, "llm_error", {"error": str(e)})
        return {
            "reply": "I'm having trouble understanding right now. Let's try again in a moment.",
            "action": "error",
        }

    product_id = intent.get("product_id")
    wants_to_buy = intent.get("wants_to_buy", False)
    reply = intent.get("reply", "")

    if product_id:
        product = catalog.get_product(product_id)
        if product:
            audit.log_event(session_id, "product_matched", {
                "product_id": product.id,
                "user_message": user_message,
            })

            # Item 2 — out-of-stock guard
            if product.stock <= 0:
                audit.log_event(session_id, "out_of_stock", {
                    "product_id": product.id,
                    "stock": product.stock,
                })
                out_reply = f"I'm sorry, but {product.name} is currently out of stock."
                _append_history(session_id, "user", user_message)
                _append_history(session_id, "assistant", out_reply)
                return {"reply": out_reply, "action": "out_of_stock"}

            if wants_to_buy:
                # Item 2.5b — explicit gate logged BEFORE any money action
                audit.log_event(session_id, "purchase_gated", {
                    "product_id": product.id,
                    "gate": "llm_confirmed_intent",
                    "user_message": user_message,
                })
                try:
                    order = payments.create_order(session_id, product.price_inr, product.id)

                    # Item 3b — upsell suggestion appended to the reply
                    base_reply = reply or f"Great, creating your order for {product.name} (₹{product.price_inr})."
                    upsell_suffix = _build_upsell_suffix(product.id, session_id)
                    final_reply = base_reply + upsell_suffix

                    _append_history(session_id, "user", user_message)
                    _append_history(session_id, "assistant", final_reply)

                    return {
                        "reply": final_reply,
                        "action": "checkout_started",
                        "order_id": order["id"],
                        "amount_inr": product.price_inr,
                        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID"),
                    }
                except Exception as e:
                    # Graceful failure — tell the user plainly, don't crash the session.
                    audit.log_event(session_id, "fallback_triggered", {"error": str(e)})
                    err_reply = (
                        "I couldn't start the payment right now -- something went wrong "
                        "on our side. You can try again in a moment, or I can hold this "
                        "item for you."
                    )
                    _append_history(session_id, "user", user_message)
                    _append_history(session_id, "assistant", err_reply)
                    return {
                        "reply": err_reply,
                        "action": "payment_error",
                        "error": str(e),
                    }

            # Product shown but not buying yet
            shown_reply = reply or f"{product.name} is ₹{product.price_inr}. Want me to start checkout?"
            _append_history(session_id, "user", user_message)
            _append_history(session_id, "assistant", shown_reply)
            return {
                "reply": shown_reply,
                "action": "product_shown",
                "product_id": product.id,
            }

    # No product matched
    no_match_reply = reply or "I couldn't find a matching product -- could you describe what you're looking for?"
    _append_history(session_id, "user", user_message)
    _append_history(session_id, "assistant", no_match_reply)
    return {
        "reply": no_match_reply,
        "action": "no_match",
    }
