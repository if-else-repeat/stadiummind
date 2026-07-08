// StadiumMind staff operations console — frontend logic.

const API_BASE = window.STADIUMMIND_API_BASE || "https://stadiummind.onrender.com";

const briefingText = document.getElementById("briefing-text");
const gateGrid = document.getElementById("gate-grid");
const incidentList = document.getElementById("incident-list");
const lastUpdated = document.getElementById("last-updated");
const refreshBtn = document.getElementById("refresh-btn");

function statusClass(status) {
  return `status-${status}`;
}

function renderGates(gateStatus) {
  gateGrid.innerHTML = "";
  gateStatus.forEach((gate) => {
    const card = document.createElement("div");
    card.className = "gate-card";

    const barsWrap = document.createElement("div");
    barsWrap.className = "floodlight-bars";
    barsWrap.setAttribute("role", "img");
    barsWrap.setAttribute(
      "aria-label",
      `${gate.gate_name} congestion level ${Math.round(gate.congestion_level * 100)} percent`
    );

    // 8-bar floodlight rig, lit proportionally to congestion
    const litBars = Math.round(gate.congestion_level * 8);
    for (let i = 0; i < 8; i++) {
      const bar = document.createElement("div");
      bar.className = "bar";
      const isLit = i < litBars;
      bar.style.height = isLit ? `${30 + i * 4}%` : "15%";
      bar.style.background = isLit
        ? (gate.congestion_level >= 0.75 ? "#E15252" : gate.congestion_level >= 0.5 ? "#F2A93B" : "#2E7D46")
        : "rgba(245,242,233,0.12)";
      barsWrap.appendChild(bar);
    }

    card.appendChild(barsWrap);

    const name = document.createElement("div");
    name.className = "gate-name";
    name.textContent = gate.gate_name;
    card.appendChild(name);

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `<span>${Math.round(gate.congestion_level * 100)}% full</span><span>${gate.queue_wait_min} min wait</span>`;
    card.appendChild(meta);

    const tag = document.createElement("span");
    tag.className = `status-tag ${statusClass(gate.status)}`;
    tag.textContent = gate.status;
    card.appendChild(tag);

    gateGrid.appendChild(card);
  });
}

function renderIncidents(incidents) {
  incidentList.innerHTML = "";
  if (!incidents.length) {
    const li = document.createElement("li");
    li.textContent = "No active incidents reported.";
    incidentList.appendChild(li);
    return;
  }
  incidents.forEach((inc) => {
    const li = document.createElement("li");
    li.className = inc.severity;
    li.innerHTML = `<strong>${inc.type.toUpperCase()}</strong> — ${inc.location}<br>${inc.note}`;
    incidentList.appendChild(li);
  });
}

async function loadDashboard() {
  briefingText.textContent = "Loading briefing…";
  try {
    const res = await fetch(`${API_BASE}/api/staff/briefing`);
    const data = await res.json();

    briefingText.innerHTML = renderLiteMarkdown(data.briefing);
    renderGates(data.summary.gate_status);
    renderIncidents(data.summary.active_incidents);
    lastUpdated.textContent = `Last updated: ${new Date(data.summary.last_updated).toLocaleString()}`;
  } catch (err) {
    briefingText.textContent = "Could not load briefing. Check that the backend is running.";
  }
}

refreshBtn.addEventListener("click", loadDashboard);
loadDashboard();
