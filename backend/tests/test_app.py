"""
Integration tests for app.py's Flask routes.

Gemini calls are monkeypatched out entirely — these tests verify our
own routing, validation, and error-handling logic, not Gemini's
availability. That keeps the suite fast, deterministic, and runnable
with zero API key or network access, matching test_decision_engine.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

import app as app_module  # noqa: E402
from services import llm_service as llm  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    # Replace every Gemini-calling function with a fast, deterministic stub.
    monkeypatch.setattr(llm, "phrase_gate_recommendation", lambda facts, language="English": "STUB_GATE_REPLY")
    monkeypatch.setattr(llm, "phrase_faq_answer", lambda q, m, language="English": "STUB_FAQ_REPLY")
    monkeypatch.setattr(llm, "phrase_sustainability_tip", lambda tip, language="English": "STUB_SUSTAIN_REPLY")
    monkeypatch.setattr(llm, "generate_staff_briefing", lambda summary: "STUB_BRIEFING")
    monkeypatch.setattr(llm, "general_chat_response", lambda msg, ctx, language="English": "STUB_GENERAL_REPLY")

    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    return app_module.app.test_client()


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_zones(client):
    res = client.get("/api/zones")
    assert res.status_code == 200
    ids = {z["id"] for z in res.get_json()}
    assert {"Z1", "Z2", "Z3", "Z4"}.issubset(ids)


def test_gate_recommend_valid(client):
    res = client.get("/api/gates/recommend?zone=Z1")
    assert res.status_code == 200
    body = res.get_json()
    assert body["message"] == "STUB_GATE_REPLY"
    assert "gate_id" in body["facts"]


def test_gate_recommend_missing_zone(client):
    res = client.get("/api/gates/recommend")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_gate_recommend_invalid_zone(client):
    res = client.get("/api/gates/recommend?zone=NOPE")
    assert res.status_code == 400


def test_faq_missing_query(client):
    res = client.get("/api/faq")
    assert res.status_code == 400


def test_faq_valid(client):
    res = client.get("/api/faq?query=can I bring a bag")
    assert res.status_code == 200
    assert res.get_json()["message"] == "STUB_FAQ_REPLY"


def test_sustainability_missing_transport(client):
    res = client.get("/api/sustainability")
    assert res.status_code == 400


def test_sustainability_valid(client):
    res = client.get("/api/sustainability?transport=train")
    assert res.status_code == 200
    assert res.get_json()["message"] == "STUB_SUSTAIN_REPLY"


def test_chat_missing_message(client):
    res = client.post("/api/assistant/chat", json={})
    assert res.status_code == 400


def test_chat_gate_intent(client):
    res = client.post(
        "/api/assistant/chat",
        json={"message": "which gate should I use", "zone": "Z2"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["intent"] == "gate"
    assert body["reply"] == "STUB_GATE_REPLY"


def test_chat_gate_intent_without_zone_falls_back_to_general(client):
    # No zone selected -> can't route, so it should fall through to
    # the general conversational handler rather than error out.
    res = client.post("/api/assistant/chat", json={"message": "which gate should I use"})
    assert res.status_code == 200
    assert res.get_json()["intent"] == "gate"
    assert res.get_json()["reply"] == "STUB_GENERAL_REPLY"


def test_chat_faq_intent(client):
    res = client.post("/api/assistant/chat", json={"message": "can I bring a bag"})
    assert res.status_code == 200
    assert res.get_json()["intent"] == "faq"


def test_chat_general_intent(client):
    res = client.post("/api/assistant/chat", json={"message": "hello there"})
    assert res.status_code == 200
    assert res.get_json()["intent"] == "general"


def test_chat_message_too_long_is_truncated_not_rejected(client):
    long_message = "gate " * 200  # well over MAX_MESSAGE_LEN
    res = client.post("/api/assistant/chat", json={"message": long_message})
    assert res.status_code == 200


def test_staff_crowd(client):
    res = client.get("/api/staff/crowd")
    assert res.status_code == 200
    body = res.get_json()
    assert "gate_status" in body
    assert "active_incidents" in body


def test_staff_briefing(client):
    res = client.get("/api/staff/briefing")
    assert res.status_code == 200
    assert res.get_json()["briefing"] == "STUB_BRIEFING"


def test_llm_failure_falls_back_gracefully(client, monkeypatch):
    def raise_error(*args, **kwargs):
        raise llm.LLMServiceError("simulated outage")

    monkeypatch.setattr(llm, "phrase_gate_recommendation", raise_error)
    res = client.get("/api/gates/recommend?zone=Z1")
    # Even when Gemini fails, the endpoint must still return a usable
    # answer built from decision_engine facts, not a 500 error.
    assert res.status_code == 200
    assert "message" in res.get_json()
