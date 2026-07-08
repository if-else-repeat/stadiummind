// format.js — tiny, dependency-free Markdown-lite renderer.
// Escapes HTML first (so nothing from an API response can inject markup),
// then converts a small safe subset of Markdown fans will actually see
// from Gemini: **bold**, *italic*, "- " bullet lists, and line breaks.

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function renderLiteMarkdown(rawText) {
  if (!rawText) return "";

  const escaped = escapeHtml(rawText);
  const lines = escaped.split("\n");
  let html = "";
  let inList = false;

  for (const line of lines) {
    const trimmed = line.trim();
    const isBullet = trimmed.startsWith("- ") || trimmed.startsWith("* ");

    if (isBullet) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${inlineFormat(trimmed.slice(2))}</li>`;
    } else {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      if (trimmed.length > 0) {
        html += `<p>${inlineFormat(trimmed)}</p>`;
      }
    }
  }
  if (inList) html += "</ul>";

  return html;
}

function inlineFormat(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<!\*)\*(?!\*)(.+?)\*(?!\*)/g, "<em>$1</em>");
}
