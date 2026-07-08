"""
llm_service.py

Thin wrapper around the Gemini API (Google AI Studio).
This module is intentionally "dumb": it never decides routing,
wait times, or safety information itself. It only takes facts
already computed by decision_engine.py and turns them into
natural, multilingual, fan-friendly text.

Keeping this separation means a hallucination here can only
affect wording/tone, never which gate someone is told to walk to.
"""

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# Reused across requests so the process keeps a warm, pooled HTTP
# connection to Gemini instead of paying a fresh TCP+TLS handshake
# on every single fan message.
_session = requests.Session()

SYSTEM_INSTRUCTION = (
    "You are StadiumMind, a helpful assistant for fans and volunteers at a "
    "FIFA World Cup 2026 host venue. You ONLY discuss stadium navigation, "
    "gates, seating zones, accessibility, transport, sustainability, safety "
    "and venue FAQs. You are given verified facts in the prompt — never "
    "invent gate numbers, wait times, or safety information beyond what is "
    "provided. If asked something unrelated to the stadium/tournament, "
    "politely redirect the user back to stadium-related help. Keep answers "
    "short, warm, and easy to read at a glance on a phone screen. "
    "Format your reply as plain conversational text for a small chat "
    "bubble: no headers, no code blocks, no numbered outlines. You may use "
    "*italic* or **bold** sparingly for emphasis, and a short '-' bullet "
    "list only if listing 3 or more distinct items."
)


class LLMServiceError(Exception):
    """Raised when the Gemini API is unreachable, rate-limited, or returns
    an unexpected response shape. Callers in app.py catch this and fall
    back to a deterministic message rather than failing the request."""


def _call_gemini(prompt: str, temperature: float = 0.4) -> str:
    """
    Send a single scoped prompt to Gemini and return the generated text.

    Retries once on a 429 (rate limit) after a short backoff, since
    those are typically transient. Thinking is disabled (thinkingBudget=0)
    because these are short phrasing/translation tasks with no need for
    deep reasoning — leaving it on would silently eat the output token
    budget and truncate replies.

    Raises:
        LLMServiceError: if the key is missing, the request ultimately
        fails, or the response has an unexpected shape. Callers are
        expected to catch this and fall back to a deterministic message.
    """
    if not GEMINI_API_KEY:
        raise LLMServiceError(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 1024,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    last_error: Optional[Exception] = None
    for attempt in range(2):  # one retry, only for transient rate limits
        try:
            resp = _session.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload,
                timeout=20,
            )
            if resp.status_code == 429 and attempt == 0:
                time.sleep(2)
                continue
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise LLMServiceError("Gemini returned no candidates.")
            finish_reason = candidates[0].get("finishReason", "")
            if finish_reason == "MAX_TOKENS":
                logger.warning("Gemini response hit MAX_TOKENS and may be truncated.")
            parts = candidates[0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except requests.exceptions.RequestException as e:
            last_error = e
            status = getattr(e.response, "status_code", None)
            if attempt == 0 and status == 429:
                time.sleep(2)
                continue
            break
        except (KeyError, IndexError) as e:
            raise LLMServiceError(f"Unexpected Gemini response shape: {e}") from e

    status = getattr(getattr(last_error, "response", None), "status_code", None)
    if status == 429:
        raise LLMServiceError(
            "Gemini API rate limit reached. Please wait a moment and try again."
        )
    raise LLMServiceError(f"Gemini API request failed: {last_error}") from last_error


def phrase_gate_recommendation(facts: dict, language: str = "English") -> str:
    """Turn a decision_engine gate recommendation dict into natural language."""
    if "error" in facts:
        prompt = (
            f"Respond in {language}. Tell the fan, kindly: {facts['error']} "
            "Suggest they ask a nearby steward for help."
        )
        return _call_gemini(prompt)

    prompt = (
        f"Respond in {language}. Using ONLY these facts, tell the fan which "
        f"gate to use and why, in 2-3 short sentences:\n"
        f"Gate: {facts['gate_name']} ({facts['gate_id']})\n"
        f"Estimated wait: {facts['estimated_wait_min']} minutes\n"
        f"Congestion level: {facts['congestion_level']}\n"
        f"Walk time from typical drop-off: {facts['walk_time_min']} minutes\n"
        f"Wheelchair accessible: {facts['wheelchair_accessible']}\n"
        f"Sensory-friendly: {facts['sensory_friendly']}"
    )
    return _call_gemini(prompt)


def phrase_faq_answer(question: str, matched_entries: list, language: str = "English") -> str:
    """Turn matched FAQ entries (or none) into a natural-language answer."""
    if not matched_entries:
        prompt = (
            f"Respond in {language}. A fan asked: \"{question}\". "
            "We have no matching info in our knowledge base. Politely say "
            "you don't have that specific info and suggest asking the "
            "nearest steward or checking the venue help desk."
        )
        return _call_gemini(prompt)

    facts_text = "\n".join(f"- {e['answer']}" for e in matched_entries)
    prompt = (
        f"Respond in {language}. A fan asked: \"{question}\". "
        f"Using ONLY these verified facts, answer clearly in 2-3 sentences:\n"
        f"{facts_text}"
    )
    return _call_gemini(prompt)


def phrase_sustainability_tip(tip: str, language: str = "English") -> str:
    """Rephrase a deterministic sustainability tip in a warmer tone."""
    prompt = (
        f"Respond in {language}. Rephrase this sustainability tip for a fan "
        f"in a warm, encouraging, one-sentence way: \"{tip}\""
    )
    return _call_gemini(prompt)


def generate_staff_briefing(crowd_summary: dict) -> str:
    """Generate a natural-language shift briefing for venue staff."""
    gate_lines = "\n".join(
        f"- {g['gate_name']}: {g['status']} "
        f"(congestion {g['congestion_level']}, wait {g['queue_wait_min']} min)"
        for g in crowd_summary["gate_status"]
    )
    incident_lines = "\n".join(
        f"- [{i['severity'].upper()}] {i['type']} at {i['location']}: {i['note']}"
        for i in crowd_summary["active_incidents"]
    ) or "None currently reported."

    prompt = (
        "Respond in English. You are briefing venue operations staff at the "
        "start of a shift. Using ONLY the verified facts below, write a "
        "short, professional briefing (max 5 sentences) that highlights the "
        "most urgent gate(s) to watch and any active incidents, and gives "
        "one clear recommended action.\n\n"
        f"Gate status:\n{gate_lines}\n\n"
        f"Active incidents:\n{incident_lines}"
    )
    return _call_gemini(prompt, temperature=0.3)


def general_chat_response(user_message: str, context: dict, language: str = "English") -> str:
    """
    Fallback conversational handler for messages that don't map cleanly
    to a specific structured intent (gate, FAQ, sustainability).
    """
    context_text = ", ".join(f"{k}: {v}" for k, v in context.items() if v)
    prompt = (
        f"Respond in {language}. Fan context: {context_text or 'none provided'}.\n"
        f"Fan message: \"{user_message}\"\n"
        "Give a short, helpful, stadium-relevant reply. If the message is "
        "unrelated to the stadium or tournament, politely redirect."
    )
    return _call_gemini(prompt)
