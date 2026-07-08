"""
app.py

StadiumMind backend API.

Design principle: every route validates its inputs, delegates FACTS to
decision_engine.py (deterministic), and delegates WORDING to
llm_service.py (Gemini). Routes never let free-text user input reach
the LLM without being scoped through a known prompt template, and every
LLM-calling route falls back to a deterministic message (via
_reply_with_fallback) if Gemini is unavailable — no route ever fails
outright just because the LLM did.
"""

import os
from typing import Callable

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from services import decision_engine as engine
from services import llm_service as llm

load_dotenv()

app = Flask(__name__)

# Restrict cross-origin access to known frontends only, instead of
# allowing any website on the internet to call this API from a browser.
# Set ALLOWED_ORIGINS on Render as a comma-separated list, e.g.
# "https://stadiummind.vercel.app,http://localhost:8000"
_allowed_origins = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
).split(",")
CORS(app, origins=[o.strip() for o in _allowed_origins if o.strip()])

# Per-IP rate limiting: protects the (limited) Gemini quota from being
# exhausted by a single abusive client, and protects the service itself
# from being overwhelmed. In-memory storage is sufficient for a single
# gunicorn worker; swap for Redis storage_uri if scaling to multiple workers.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour"],
    storage_uri="memory://",
)

VALID_ZONES = {z["id"] for z in engine.get_zones()}

# Input length caps, named rather than left as inline magic numbers.
ZONE_MAX_LEN = 10
TRANSPORT_MAX_LEN = 20
MESSAGE_MAX_LEN = 500
LANGUAGE_MAX_LEN = 40

CHAT_FALLBACK_MESSAGE = (
    "I'm having trouble reaching the assistant service right now. "
    "Please ask a nearby steward for immediate help."
)


def _bad_request(message: str):
    """Return a consistent 400 JSON error response."""
    return jsonify({"error": message}), 400


def _clean_str(value, max_len: int) -> str:
    """Coerce a request value to a trimmed, length-capped string."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_len]


def _reply_with_fallback(llm_call: Callable[[], str], fallback_call: Callable[[], str], log_label: str) -> str:
    """
    Call an LLM phrasing function, falling back to a deterministic
    message if Gemini is unavailable. Centralizes the try/except so
    every LLM-calling route shares identical, tested failure handling
    instead of repeating the same block.
    """
    try:
        return llm_call()
    except llm.LLMServiceError as e:
        app.logger.warning("LLM fallback used (%s): %s", log_label, e)
        return fallback_call()


@app.route("/api/health", methods=["GET"])
def health():
    """Liveness check used by uptime monitors and deploy smoke tests."""
    return jsonify({"status": "ok"})


@app.route("/api/zones", methods=["GET"])
def zones():
    """List all seating zones."""
    return jsonify(engine.get_zones())


@app.route("/api/gates/recommend", methods=["GET"])
def recommend_gate():
    """Recommend the best gate for a fan's zone and accessibility needs."""
    zone_id = _clean_str(request.args.get("zone", ""), ZONE_MAX_LEN)
    language = _clean_str(request.args.get("language", "English"), LANGUAGE_MAX_LEN)
    needs_wheelchair = request.args.get("wheelchair", "false").lower() == "true"
    needs_sensory = request.args.get("sensory", "false").lower() == "true"

    if zone_id not in VALID_ZONES:
        return _bad_request(
            f"Invalid or missing 'zone'. Must be one of: {sorted(VALID_ZONES)}"
        )

    facts = engine.recommend_gate(zone_id, needs_wheelchair, needs_sensory)
    message = _reply_with_fallback(
        lambda: llm.phrase_gate_recommendation(facts, language),
        lambda: _fallback_gate_message(facts),
        "gate",
    )
    return jsonify({"facts": facts, "message": message})


@app.route("/api/faq", methods=["GET"])
def faq():
    """Answer a free-text venue FAQ question, grounded in the local knowledge base."""
    query = _clean_str(request.args.get("query", ""), MESSAGE_MAX_LEN)
    language = _clean_str(request.args.get("language", "English"), LANGUAGE_MAX_LEN)

    if not query:
        return _bad_request("Missing 'query' parameter.")

    matches = engine.search_faq(query, top_k=2)
    message = _reply_with_fallback(
        lambda: llm.phrase_faq_answer(query, matches, language),
        lambda: _fallback_faq_message(matches),
        "faq",
    )
    return jsonify({"matches": matches, "message": message})


@app.route("/api/sustainability", methods=["GET"])
def sustainability():
    """Return an eco tip tailored to the fan's transport mode."""
    transport_mode = _clean_str(request.args.get("transport", ""), TRANSPORT_MAX_LEN)
    language = _clean_str(request.args.get("language", "English"), LANGUAGE_MAX_LEN)

    if not transport_mode:
        return _bad_request("Missing 'transport' parameter.")

    tip = engine.get_sustainability_tip(transport_mode)
    message = _reply_with_fallback(
        lambda: llm.phrase_sustainability_tip(tip, language),
        lambda: tip,
        "sustainability",
    )
    return jsonify({"tip": tip, "message": message})


@app.route("/api/assistant/chat", methods=["POST"])
@limiter.limit("20 per minute")
def chat():
    """
    Free-text chat endpoint. Classifies intent, routes to the matching
    decision_engine facts, then phrases the reply through Gemini —
    falling back to a generic message if Gemini itself is unavailable.
    """
    body = request.get_json(silent=True) or {}

    user_message = _clean_str(body.get("message", ""), MESSAGE_MAX_LEN)
    language = _clean_str(body.get("language", "English"), LANGUAGE_MAX_LEN)
    zone_id = _clean_str(body.get("zone", ""), ZONE_MAX_LEN)
    needs_wheelchair = bool(body.get("wheelchair", False))
    needs_sensory = bool(body.get("sensory", False))
    transport_mode = _clean_str(body.get("transport", ""), TRANSPORT_MAX_LEN)

    if not user_message:
        return _bad_request("Missing 'message' field.")

    intent = _detect_intent(user_message)

    def call_llm() -> str:
        if intent == "gate" and zone_id in VALID_ZONES:
            facts = engine.recommend_gate(zone_id, needs_wheelchair, needs_sensory)
            return llm.phrase_gate_recommendation(facts, language)
        if intent == "sustainability" and transport_mode:
            tip = engine.get_sustainability_tip(transport_mode)
            return llm.phrase_sustainability_tip(tip, language)
        if intent == "faq":
            matches = engine.search_faq(user_message, top_k=2)
            return llm.phrase_faq_answer(user_message, matches, language)
        context = {
            "zone": zone_id,
            "transport": transport_mode,
            "wheelchair_needed": needs_wheelchair,
            "sensory_friendly_needed": needs_sensory,
        }
        return llm.general_chat_response(user_message, context, language)

    reply = _reply_with_fallback(call_llm, lambda: CHAT_FALLBACK_MESSAGE, "chat")
    return jsonify({"intent": intent, "reply": reply})


@app.route("/api/staff/crowd", methods=["GET"])
def staff_crowd():
    """Return the live gate congestion summary for the staff dashboard."""
    return jsonify(engine.get_crowd_summary())


@app.route("/api/staff/briefing", methods=["GET"])
def staff_briefing():
    """Return an AI-generated shift briefing built from live crowd data."""
    summary = engine.get_crowd_summary()
    briefing = _reply_with_fallback(
        lambda: llm.generate_staff_briefing(summary),
        lambda: _fallback_briefing(summary),
        "briefing",
    )
    return jsonify({"summary": summary, "briefing": briefing})


def _detect_intent(message: str) -> str:
    """
    Lightweight keyword-based intent classifier.
    Kept simple and transparent on purpose — no LLM call needed just
    to route a request, which saves latency and API cost.
    """
    text = message.lower()

    gate_keywords = ["gate", "entrance", "which way", "how do i get in", "route", "direction"]
    sustainability_keywords = ["sustainab", "carbon", "eco", "recycle", "emission", "green"]
    faq_keywords = [
        "bag", "re-entry", "reentry", "lost", "prayer", "wheelchair",
        "parking", "shuttle", "train", "first aid", "medical", "policy",
    ]

    if any(keyword in text for keyword in gate_keywords):
        return "gate"
    if any(keyword in text for keyword in sustainability_keywords):
        return "sustainability"
    if any(keyword in text for keyword in faq_keywords):
        return "faq"
    return "general"


def _fallback_gate_message(facts: dict) -> str:
    """Plain-language gate recommendation used when Gemini is unavailable."""
    if "error" in facts:
        return facts["error"]
    return f"Use {facts['gate_name']}. Estimated wait: {facts['estimated_wait_min']} minutes."


def _fallback_faq_message(matches: list) -> str:
    """Plain-language FAQ answer used when Gemini is unavailable."""
    if not matches:
        return "I don't have specific info on that. Please ask a nearby steward."
    return matches[0]["answer"]


def _fallback_briefing(summary: dict) -> str:
    """Plain-language staff briefing used when Gemini is unavailable."""
    busiest = summary["gate_status"][0] if summary["gate_status"] else None
    if not busiest:
        return "No gate data available."
    return (
        f"Busiest gate: {busiest['gate_name']} ({busiest['status']}, "
        f"{busiest['queue_wait_min']} min wait). "
        f"{len(summary['active_incidents'])} active incident(s) reported."
    )


@app.errorhandler(429)
def rate_limit_exceeded(e):
    """Return a JSON (not HTML) error body when a client is rate-limited."""
    return jsonify({"error": "Too many requests. Please wait a moment and try again."}), 429


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
