"""
Unit tests for decision_engine.py.

These test pure, deterministic logic only — no network calls,
no LLM, no Flask app context. Fast and safe to run anywhere,
including in CI with zero API keys configured.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import decision_engine as engine  # noqa: E402


def test_get_zones_returns_known_zones():
    zones = engine.get_zones()
    zone_ids = {z["id"] for z in zones}
    assert {"Z1", "Z2", "Z3", "Z4"}.issubset(zone_ids)


def test_recommend_gate_valid_zone():
    result = engine.recommend_gate("Z1")
    assert "error" not in result
    assert result["gate_id"] in {"GATE_A", "GATE_C"}


def test_recommend_gate_invalid_zone_returns_error():
    result = engine.recommend_gate("Z999")
    assert "error" in result


def test_recommend_gate_wheelchair_filter_excludes_non_accessible():
    result = engine.recommend_gate("Z1", needs_wheelchair=True)
    assert "error" not in result
    assert result["wheelchair_accessible"] is True
    # GATE_C serves Z1 but is not wheelchair accessible, so must not be chosen
    assert result["gate_id"] != "GATE_C"


def test_recommend_gate_sensory_friendly_filter():
    result = engine.recommend_gate("Z3", needs_sensory_friendly=True)
    assert "error" not in result
    assert result["sensory_friendly"] is True


def test_recommend_gate_impossible_combo_returns_error():
    # Z1 has no sensory-friendly gate serving it in the mock data
    result = engine.recommend_gate("Z1", needs_sensory_friendly=True)
    assert "error" in result


def test_recommend_gate_prefers_lower_congestion():
    # Both GATE_A and GATE_C serve Z1; GATE_A has lower congestion in mock data
    result = engine.recommend_gate("Z1")
    assert result["gate_id"] == "GATE_A"


def test_sustainability_tip_known_mode():
    tip = engine.get_sustainability_tip("train")
    assert "rail" in tip.lower() or "train" in tip.lower() or "carbon" in tip.lower()


def test_sustainability_tip_unknown_mode_has_fallback():
    tip = engine.get_sustainability_tip("teleporter")
    assert isinstance(tip, str) and len(tip) > 0


def test_crowd_summary_structure():
    summary = engine.get_crowd_summary()
    assert "gate_status" in summary
    assert "active_incidents" in summary
    assert len(summary["gate_status"]) == 4
    # Should be sorted by congestion descending
    levels = [g["congestion_level"] for g in summary["gate_status"]]
    assert levels == sorted(levels, reverse=True)


def test_congestion_label_thresholds():
    assert engine._congestion_label(0.9) == "critical"
    assert engine._congestion_label(0.6) == "busy"
    assert engine._congestion_label(0.3) == "moderate"
    assert engine._congestion_label(0.1) == "clear"


def test_search_faq_finds_relevant_entry():
    results = engine.search_faq("Can I bring a backpack inside?")
    assert len(results) >= 1
    assert results[0]["id"] == "faq_bags"


def test_search_faq_no_match_returns_empty():
    results = engine.search_faq("what time does the sun rise on mars")
    assert results == []
