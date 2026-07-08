# StadiumMind

**A GenAI-powered fan assistant and operations console for FIFA World Cup 2026 venues**

Submission for **Challenge 4: Smart Stadiums & Tournament Operations**

**Live demo:** https://stadiummind.vercel.app
**Backend API:** https://stadiummind.onrender.com

---

## 1. Problem Statement

Mega-events like the FIFA World Cup 2026 bring together fans who don't speak
a common language, arrive through unfamiliar venues, and need accurate,
real-time answers under time pressure — while operations staff must
simultaneously track crowd density and incidents across a stadium far too
large to observe directly. Existing signage and static apps can't adapt to
an individual fan's language, accessibility needs, or the venue's live
condition, and staff are often left cross-referencing multiple disconnected
systems during a live match.

**StadiumMind** addresses this with a single, lightweight system: one
GenAI-powered assistant, viewed through two purpose-built interfaces — a
conversational assistant for fans, and a live operations console for staff.

---

## 2. Chosen Vertical

**Smart Stadiums & Tournament Operations**, addressing six of the
challenge's named focus areas directly:

| Focus area | Delivered as |
|---|---|
| Navigation | Real-time, congestion-aware gate recommendations |
| Crowd management | Live gate congestion tracking and staff alerting |
| Accessibility | Wheelchair- and sensory-friendly-aware routing |
| Multilingual assistance | Every reply generated in the fan's chosen language |
| Sustainability | Transport-mode-based eco guidance |
| Operational intelligence | AI-generated shift briefings from live venue data |

---

## 3. Approach & Logic

The system is built on one core design principle: **facts and language are
generated separately.**

```
Live venue data (gates, zones, congestion, incidents, FAQ)
                    │
                    ▼
      decision_engine.py   →  deterministic, rule-based, unit-tested
      (routing, congestion scoring, sustainability tips, FAQ retrieval)
                    │
                    ▼
      llm_service.py       →  Gemini 3.5 Flash (Google AI Studio)
      (natural-language phrasing, translation, summarization — nothing else)
                    │
                    ▼
      Fan-facing reply / staff briefing, in plain, readable language
```

**Why this matters in a stadium context:** a generative model should never
be the system deciding which gate is safe to route thousands of people
through, or inventing a wait time — that has to come from real operational
data. Gemini's role is deliberately narrower: turning verified facts into a
clear, warm sentence a stressed fan can act on immediately, in their own
language, and turning a page of gate telemetry into a five-second staff
briefing.

This separation also makes the system **fail safely**: if the Gemini API is
slow, rate-limited, or unreachable, every endpoint still returns a correct
answer built directly from `decision_engine.py` (see the `_fallback_*`
functions in `app.py`). No safety-relevant information ever depends on the
LLM being available.

---

## 4. How the Solution Works

### Architecture

```
stadiummind/
├── backend/                     Flask API (deployed on Render)
│   ├── app.py                   Routing, input validation, fallbacks
│   ├── services/
│   │   ├── decision_engine.py   Deterministic logic — unit tested, no network calls
│   │   └── llm_service.py       Gemini API wrapper — phrasing only
│   ├── data/                    Simulated live venue data (JSON)
│   ├── tests/
│   │   └── test_decision_engine.py   13 unit tests, zero API dependency
│   └── requirements.txt
├── frontend/                    Static site (deployed on Vercel)
│   ├── index.html               Fan assistant
│   ├── staff.html               Operations console
│   ├── css/style.css
│   └── js/ (app.js, staff.js)
├── .env.example
└── README.md
```

### Fan assistant flow (example: "which gate should I use?")

1. The frontend sends the fan's message, selected zone, accessibility
   needs, and language to `POST /api/assistant/chat`.
2. `app.py` validates the input and classifies intent as `gate`.
3. `decision_engine.recommend_gate()` filters gates serving that zone,
   applies any accessibility filters, and selects the least-congested valid
   match using live congestion data.
4. `llm_service.phrase_gate_recommendation()` sends those exact facts to
   Gemini 3.5 Flash with a scoped system prompt, asking for a short, warm
   reply in the fan's chosen language.
5. If Gemini is unavailable, `app.py` falls back to a plain-language
   sentence built directly from the same facts — the fan still gets a
   correct, actionable answer.

### Staff console flow

`staff.html` polls `/api/staff/crowd` and `/api/staff/briefing`, rendering
live gate congestion as floodlight-style intensity bars and displaying an
AI-generated shift briefing — a five-sentence summary of which gates need
attention and what to do next, generated from the same underlying data the
fan assistant uses.

### Using the live demo

1. Open the **live demo link** above.
2. Select your seating zone, preferred language, and any accessibility
   needs.
3. Tap a quick-action button (e.g. *Find my gate*) or type a free-text
   question.
4. Visit `/staff.html` on the same domain to see the live operations
   console and shift briefing.

---

## 5. Running Locally

```bash
git clone https://github.com/<your-username>/stadiummind.git
cd stadiummind/backend
pip install -r requirements.txt

cp ../.env.example .env
# add your Gemini API key from https://aistudio.google.com/app/apikey
nano .env

python app.py
```

Serve `frontend/` with any static file server (or open `index.html`
directly) and point `API_BASE` in `js/app.js` / `js/staff.js` at your local
backend.

### Running tests

```bash
cd backend
python -m pytest tests/ -v
```

31 tests cover both the deterministic decision engine
(`test_decision_engine.py`) and the Flask API layer end-to-end
(`test_app.py`) — including input validation, invalid-zone handling, intent
routing, and the LLM-failure fallback path. All Gemini calls are mocked in
`test_app.py`, so the full suite runs in under a second with no API key or
network access required. Tests run automatically on every push via
GitHub Actions (`.github/workflows/tests.yml`).

---

## 6. Deployment

- **Backend:** Flask app deployed on **Render** as a web service
  (`gunicorn app:app`), with the Gemini API key stored as an environment
  variable in Render's dashboard — never committed to source control.
- **Frontend:** Static site deployed on **Vercel**, with its Root Directory
  set to `frontend/`. No environment variables are needed here, since a
  no-build static site has no build step to inject them into — the backend
  URL is set directly in `js/app.js` and `js/staff.js`.

---

## 7. Security

- The Gemini API key lives only in an environment variable on Render; a
  template is provided in `.env.example`, and the real `.env` is
  git-ignored.
- The browser never talks to Gemini directly — only to our own backend —
  so the key is never exposed client-side.
- All request inputs are length-capped, type-checked, and validated against
  a whitelist of known zones before use.
- The Gemini system prompt explicitly scopes the assistant to
  stadium/tournament topics and instructs it to rely only on the facts
  it's given, reducing hallucination risk and prompt-injection surface.
- No personal data is collected or persisted; every request is stateless.
- Cross-origin requests are restricted to explicitly allowed frontend
  origins (`ALLOWED_ORIGINS`), not open to any site on the internet.
- Per-IP rate limiting (Flask-Limiter) protects both the service and the
  Gemini quota from being exhausted by a single abusive or malfunctioning
  client — 100 requests/hour overall, 20/minute on the chat endpoint
  specifically, since that's the one calling the LLM.

---

## 7a. Performance & Efficiency

- **In-memory data caching** (`decision_engine._cache`): venue reference
  data (gates, zones, FAQ) is read from disk once per process and reused
  for every subsequent request, instead of re-reading and re-parsing JSON
  on every API call.
- **Pooled HTTP connections** (`llm_service._session`): a single
  `requests.Session` is reused across all Gemini calls, avoiding a fresh
  TCP/TLS handshake per request.
- **Automatic retry on rate limits**: a transient `429` from Gemini
  triggers one short backoff-and-retry before falling back to the
  deterministic answer, rather than failing the whole request outright.
- **No LLM call for routing**: intent classification (`_detect_intent()`)
  is a lightweight keyword check, not a model call — this saves an entire
  API round-trip on every message just to decide *how* to answer it.
- **Zero build step, zero database**: the frontend is static HTML/CSS/JS
  and the backend has no persistence layer, keeping both cold-start time
  and total resource footprint minimal (~50KB compressed).

---

## 8. Assumptions

- No live access to FIFA's ticketing, IoT, or crowd-sensor systems was
  available. Gate layout, congestion levels, and incidents in
  `backend/data/*.json` are a realistic simulated dataset for one sample
  venue (modeled on a real World Cup 2026 host stadium's general layout).
  `decision_engine.py`'s public functions are written so this data source
  could be swapped for a live feed with no changes to the API contract.
- The Gemini model is configurable via the `GEMINI_MODEL` environment
  variable (defaulting to `gemini-3.5-flash`), so the project can move to
  newer Gemini releases without a code change.
- The staff console is advisory: it informs a human decision-maker and does
  not automatically trigger physical actions like gate closures, which
  would require integration with real venue control systems.

---

## 9. Tech Stack

- **Backend:** Python, Flask, Flask-CORS, Gunicorn
- **AI:** Gemini 3.5 Flash (Google AI Studio) via the REST `generateContent`
  API — no SDK dependency, minimal footprint
- **Frontend:** Vanilla HTML, CSS, JavaScript — no build step, loads
  instantly on mobile networks
- **Testing:** Pytest
- **Hosting:** Render (backend), Vercel (frontend)
