"""
Conversational checkout agent.

Takes a free-text user message, figures out what product they want
(using the catalog + an LLM for intent parsing), and drives the
checkout via payments.py. Every step writes to the audit trail.

Swap LLM_PROVIDER in .env between "groq" and "gemini" -- both are
wired here so you can demo whichever key you have first.
"""

import os
import json
from dotenv import load_dotenv

from . import catalog, payments, audit

load_dotenv()

SYSTEM_PROMPT = """You are a shopping assistant for an online store. \
Given the user's message and a product catalog, decide:
1. Which single product (if any) the user most likely wants, by id.
2. Whether they've confirmed they want to buy it (vs just browsing/asking).

Respond ONLY with JSON in this exact shape, no other text:
{"product_id": "<id or null>", "wants_to_buy": true or false, "reply": "<short natural reply to the user>"}
"""


def _call_groq(user_message: str, catalog_text: str) -> dict:
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + f"\n\nCatalog:\n{catalog_text}"},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )
    return json.loads(completion.choices[0].message.content)


def _call_gemini(user_message: str, catalog_text: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT + f"\n\nCatalog:\n{catalog_text}",
    )
    response = model.generate_content(
        user_message,
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def _parse_intent(user_message: str) -> dict:
    catalog_text = "\n".join(
        f"- id={p.id} | {p.name} | \u20b9{p.price_inr} | {p.description}"
        for p in catalog.get_catalog()
    )
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "gemini":
        return _call_gemini(user_message, catalog_text)
    return _call_groq(user_message, catalog_text)


def handle_message(session_id: str, user_message: str) -> dict:
    """
    Main entry point: one turn of the conversation.
    Returns a dict the API layer can send straight back to the frontend.
    """
    try:
        intent = _parse_intent(user_message)
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

            if getattr(product, 'stock', 0) <= 0:
                audit.log_event(session_id, "out_of_stock", {"product_id": product.id, "stock": getattr(product, 'stock', 0)})
                return {
                    "reply": f"I'm sorry, but {product.name} is currently out of stock.",
                    "action": "out_of_stock",
                }

            if wants_to_buy:
                # Item 2.5b: Explicit gate — log the LLM's decision BEFORE
                # any money action executes. This creates a human-readable
                # paper trail satisfying the "bounded and gated" criterion.
                audit.log_event(session_id, "purchase_gated", {
                    "product_id": product.id,
                    "gate": "llm_confirmed_intent",
                    "user_message": user_message,
                })
                try:
                    order = payments.create_order(session_id, product.price_inr, product.id)
                    return {
                        "reply": reply or f"Great, creating your order for {product.name} (\u20b9{product.price_inr}).",
                        "action": "checkout_started",
                        "order_id": order["id"],
                        "amount_inr": product.price_inr,
                        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID"),
                    }
                except Exception as e:
                    # Graceful failure: tell the user plainly, don't crash the session.
                    audit.log_event(session_id, "fallback_triggered", {"error": str(e)})
                    return {
                        "reply": "I couldn't start the payment right now -- something went wrong on our side. You can try again in a moment, or I can hold this item for you.",
                        "action": "payment_error",
                        "error": str(e),
                    }

            return {
                "reply": reply or f"{product.name} is \u20b9{product.price_inr}. Want me to start checkout?",
                "action": "product_shown",
                "product_id": product.id,
            }

    return {
        "reply": reply or "I couldn't find a matching product -- could you describe what you're looking for?",
        "action": "no_match",
    }
