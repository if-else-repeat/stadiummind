// StadiumMind fan assistant — frontend logic.
// Talks only to our own backend (never calls Gemini directly from the
// browser), so no API key is ever exposed to the client.

const API_BASE = window.STADIUMMIND_API_BASE || "https://stadiummind.onrender.com";

const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

const zoneSelect = document.getElementById("zone-select");
const langSelect = document.getElementById("lang-select");
const wheelchairCheck = document.getElementById("wheelchair-check");
const sensoryCheck = document.getElementById("sensory-check");
const transportSelect = document.getElementById("transport-select");

function appendMessage(text, sender, isError = false) {
  const div = document.createElement("div");
  div.className = `msg ${sender}${isError ? " error" : ""}`;
  if (sender === "bot") {
    div.innerHTML = renderLiteMarkdown(text);
  } else {
    div.textContent = text;
  }
  chatLog.appendChild(div);
  div.scrollIntoView({ behavior: "smooth", block: "end" });
  return div;
}

function showTypingIndicator() {
  const div = document.createElement("div");
  div.className = "msg bot typing";
  div.setAttribute("aria-label", "StadiumMind is typing");
  div.innerHTML = `<span class="dot"></span><span class="dot"></span><span class="dot"></span>`;
  chatLog.appendChild(div);
  div.scrollIntoView({ behavior: "smooth", block: "end" });
  return div;
}

function setSending(isSending) {
  chatInput.disabled = isSending;
  chatForm.querySelector("button[type='submit']").disabled = isSending;
}

async function sendMessage(message) {
  appendMessage(message, "user");
  setSending(true);
  const typingEl = showTypingIndicator();

  const payload = {
    message,
    language: langSelect.value,
    zone: zoneSelect.value,
    wheelchair: wheelchairCheck.checked,
    sensory: sensoryCheck.checked,
    transport: transportSelect.value,
  };

  try {
    const res = await fetch(`${API_BASE}/api/assistant/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    typingEl.remove();

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      appendMessage(errBody.error || "Something went wrong. Please try again.", "bot", true);
      return;
    }

    const data = await res.json();
    appendMessage(data.reply, "bot");
  } catch (err) {
    typingEl.remove();
    appendMessage(
      "Couldn't reach StadiumMind right now. Check your connection or ask a nearby steward.",
      "bot",
      true
    );
  } finally {
    setSending(false);
    chatInput.focus();
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  sendMessage(text);
});

document.querySelectorAll("[data-quick]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const quickText = btn.getAttribute("data-quick");
    if (quickText.toLowerCase().includes("gate") && !zoneSelect.value) {
      appendMessage("Please select your seating zone above first, so I can find your best gate.", "bot", true);
      zoneSelect.focus();
      return;
    }
    sendMessage(quickText);
  });
});
