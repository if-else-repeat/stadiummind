"""
decision_engine.py

All deterministic, rule-based logic for StadiumMind lives here.
No LLM calls happen in this file on purpose: routing, wait-time,
and safety-relevant decisions must be predictable and testable,
not generated. The LLM layer (llm_service.py) only phrases these
facts in natural language / another language.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Congestion-score tuning: how heavily live congestion is weighted
# against raw walk time when ranking candidate gates. Higher = crowding
# matters more than distance.
CONGESTION_WEIGHT = 15

# Thresholds for turning a 0.0-1.0 congestion level into a human label.
CRITICAL_THRESHOLD = 0.75
BUSY_THRESHOLD = 0.5
MODERATE_THRESHOLD = 0.25

_DEFAULT_GATE_STATE = {"congestion_level": 0, "queue_wait_min": 0}


@lru_cache(maxsize=None)
def _load_json(filename: str) -> dict:
    """
    Load and cache a JSON data file by name.

    Cached for the life of the process: venue reference data (gates,
    zones, FAQ) never changes at runtime, so repeated requests reuse
    the parsed result instead of re-reading and re-parsing from disk
    on every call.
    """
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_crowd_state() -> None:
    """
    Drop all cached data files so the next read picks up fresh content.

    Call this if/when a real live feed replaces the mock JSON files.
    Clears the whole cache rather than a single entry — simpler, and
    the cost of one extra disk read on the next call is negligible.
    """
    _load_json.cache_clear()


def get_gates() -> list[dict]:
    """Return the full list of venue gates and their static attributes."""
    return _load_json("gates.json")["gates"]


def get_zones() -> list[dict]:
    """Return the full list of seating zones."""
    return _load_json("zones.json")["zones"]


def get_crowd_state() -> dict:
    """Return the current (simulated) live congestion and incident data."""
    return _load_json("crowd_state.json")


def get_faq_entries() -> list[dict]:
    """Return the local FAQ knowledge base used by search_faq()."""
    return _load_json("faq.json")


def _congestion_for_gate(gate_id: str, crowd: dict) -> dict:
    """Look up a gate's live congestion state, defaulting to 'clear'."""
    return crowd.get(gate_id, _DEFAULT_GATE_STATE)


def _gate_score(gate: dict, crowd: dict) -> float:
    """
    Rank a candidate gate: lower score is better.

    Congestion dominates the score (see CONGESTION_WEIGHT) so a fan is
    never routed into a badly backed-up gate just because it's a
    slightly shorter walk.
    """
    state = _congestion_for_gate(gate["id"], crowd)
    return state["congestion_level"] * CONGESTION_WEIGHT + gate["base_walk_time_min"]


def recommend_gate(
    zone_id: str,
    needs_wheelchair: bool = False,
    needs_sensory_friendly: bool = False,
) -> dict:
    """
    Pick the best gate for a fan given their seating zone and
    accessibility needs, ranked by live congestion level.

    Args:
        zone_id: The fan's seating zone (e.g. "Z1").
        needs_wheelchair: If True, only wheelchair-accessible gates qualify.
        needs_sensory_friendly: If True, only sensory-friendly gates qualify.

    Returns:
        A dict describing the chosen gate and its live status, or a dict
        with an "error" key if no gate matches the given filters.
    """
    gates = get_gates()
    crowd = get_crowd_state()["gate_congestion"]

    candidates = [g for g in gates if zone_id in g["serves_zones"]]
    if needs_wheelchair:
        candidates = [g for g in candidates if g["wheelchair_accessible"]]
    if needs_sensory_friendly:
        candidates = [g for g in candidates if g["sensory_friendly"]]

    if not candidates:
        return {
            "error": (
                f"No matching gate found for zone '{zone_id}' "
                f"with the requested accessibility filters."
            )
        }

    best = min(candidates, key=lambda g: _gate_score(g, crowd))
    state = _congestion_for_gate(best["id"], crowd)

    return {
        "gate_id": best["id"],
        "gate_name": best["name"],
        "estimated_wait_min": state["queue_wait_min"],
        "congestion_level": state["congestion_level"],
        "walk_time_min": best["base_walk_time_min"],
        "wheelchair_accessible": best["wheelchair_accessible"],
        "sensory_friendly": best["sensory_friendly"],
    }


_SUSTAINABILITY_TIPS = {
    "car": (
        "Consider carpooling or using Lot 5 park-and-ride shuttles "
        "next time to cut emissions."
    ),
    "shuttle": (
        "Great choice — shuttle transit produces far less CO2 per fan "
        "than driving alone."
    ),
    "train": "Rail is one of the lowest-carbon ways to reach the venue. Nicely done.",
    "walk": "Walking or cycling in has zero transport emissions — the best option available.",
    "bike": "Cycling in is emissions-free. Secure bike racks are available near Gate D.",
}

_DEFAULT_SUSTAINABILITY_TIP = (
    "Whichever way you arrived, remember to use the recycling and "
    "compost stations at every concourse level."
)


def get_sustainability_tip(transport_mode: str) -> str:
    """Return a short eco tip tailored to how the fan is arriving."""
    return _SUSTAINABILITY_TIPS.get(transport_mode.lower(), _DEFAULT_SUSTAINABILITY_TIP)


def _congestion_label(level: float) -> str:
    """Convert a 0.0-1.0 congestion level into a human-readable status."""
    if level >= CRITICAL_THRESHOLD:
        return "critical"
    if level >= BUSY_THRESHOLD:
        return "busy"
    if level >= MODERATE_THRESHOLD:
        return "moderate"
    return "clear"


def get_crowd_summary() -> dict:
    """
    Build the aggregated view used by the staff operations dashboard:
    every gate's live status, busiest first, plus active incidents.
    """
    state = get_crowd_state()
    gate_names = {g["id"]: g["name"] for g in get_gates()}

    ranked = sorted(
        state["gate_congestion"].items(),
        key=lambda kv: kv[1]["congestion_level"],
        reverse=True,
    )

    return {
        "last_updated": state["last_updated"],
        "gate_status": [
            {
                "gate_id": gate_id,
                "gate_name": gate_names.get(gate_id, gate_id),
                "congestion_level": info["congestion_level"],
                "queue_wait_min": info["queue_wait_min"],
                "status": _congestion_label(info["congestion_level"]),
            }
            for gate_id, info in ranked
        ],
        "active_incidents": state["incidents"],
    }


def search_faq(query: str, top_k: int = 1) -> list[dict]:
    """
    Simple keyword-overlap retrieval over the local FAQ knowledge base.

    Deliberately not a vector DB: keeps the repo tiny and dependency-free
    while still giving the LLM layer grounded facts to work from (RAG-lite).

    Args:
        query: The fan's free-text question.
        top_k: Maximum number of matching FAQ entries to return.

    Returns:
        Up to top_k FAQ entries, best keyword match first. Empty list
        if nothing matches.
    """
    query_lower = query.lower()

    scored: list[tuple[int, dict]] = []
    for entry in get_faq_entries():
        matches = sum(1 for keyword in entry["keywords"] if keyword in query_lower)
        if matches > 0:
            scored.append((matches, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]
