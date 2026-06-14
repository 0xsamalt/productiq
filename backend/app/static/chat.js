// Unified diagnostic chat: one input that supports text + optional image attachment.
// If a file is attached → POST multipart to /diagnose-image (text becomes the note).
// Otherwise → POST JSON to /diagnose with conversation history.
(function () {
  const productId = window.MANTIS_PRODUCT_ID;
  const messagesEl = document.getElementById("messages");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const resetBtn = document.getElementById("reset-btn");
  const fileInput = document.getElementById("chat-file");
  const attachmentRow = document.getElementById("attachment-preview");
  const attachmentThumb = document.getElementById("attachment-thumb");
  const attachmentName = document.getElementById("attachment-name");
  const attachmentSize = document.getElementById("attachment-size");
  const attachmentClear = document.getElementById("attachment-clear");

  let history = []; // [{role, content}]
  let pendingFile = null; // File | null
  let pendingDataUrl = null; // string | null

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }

  function citationsHTML(citations) {
    if (!citations || !citations.length) return "";
    const pills = citations.slice(0, 4).map(c => {
      const src = c.source || "doc";
      const pg = c.page != null && c.page !== "None" ? ` p.${c.page}` : "";
      return `<span class="cite-pill" title="${escapeHtml((c.text||'').slice(0,200))}">${escapeHtml(src)}${pg}</span>`;
    }).join("");
    return `<div class="mt-2">${pills}</div>`;
  }

  function appendMsg({ role, content, mode, citations, image }) {
    const bubble = document.createElement("div");
    bubble.className = "rounded-lg p-3 " + (role === "user" ? "msg-user" : "msg-assistant");
    if (mode === "ASK") bubble.classList.add("msg-ask");
    if (mode === "DIAGNOSE") bubble.classList.add("msg-diagnose");

    let badge = "";
    if (role === "assistant" && mode && mode !== "UNKNOWN") {
      badge = `<span class="text-[10px] font-bold tracking-widest ${mode==='ASK'?'text-emerald-700':'text-amber-700'} mr-2">${mode}</span>`;
    }

    let imgHTML = "";
    if (image) {
      imgHTML = `<img src="${image}" class="rounded mb-2 max-h-48 border border-zinc-200" />`;
    }

    bubble.innerHTML = `${imgHTML}<div>${badge}<span>${escapeHtml(content).replace(/\n/g, "<br/>")}</span></div>${citationsHTML(citations)}`;
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendTyping() {
    const el = document.createElement("div");
    el.id = "typing";
    el.className = "text-xs text-zinc-400 italic px-2";
    el.textContent = "diagnosing…";
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  function removeTyping() {
    const el = document.getElementById("typing");
    if (el) el.remove();
  }

  function clearAttachment() {
    pendingFile = null;
    pendingDataUrl = null;
    fileInput.value = "";
    attachmentRow.classList.add("hidden");
  }

  function showAttachment(file) {
    pendingFile = file;
    const reader = new FileReader();
    reader.onload = () => {
      pendingDataUrl = reader.result;
      attachmentThumb.src = pendingDataUrl;
      attachmentName.textContent = file.name;
      attachmentSize.textContent = ` · ${(file.size / 1024).toFixed(0)} KB`;
      attachmentRow.classList.remove("hidden");
    };
    reader.readAsDataURL(file);
  }

  fileInput.addEventListener("change", e => {
    const f = e.target.files[0];
    if (f) showAttachment(f);
  });

  attachmentClear.addEventListener("click", clearAttachment);

  async function sendTextOnly(message) {
    history.push({ role: "user", content: message });
    appendMsg({ role: "user", content: message });
    appendTyping();
    try {
      const res = await fetch(`/api/products/${productId}/diagnose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ history: history.slice(0, -1), message }),
      });
      removeTyping();
      if (!res.ok) {
        appendMsg({ role: "assistant", content: `(error ${res.status}) ${await res.text()}` });
        return;
      }
      const data = await res.json();
      history.push({ role: "assistant", content: data.reply });
      appendMsg({ role: "assistant", content: data.reply, mode: data.mode, citations: data.citations });
    } catch (e) {
      removeTyping();
      appendMsg({ role: "assistant", content: `(network error) ${e.message}` });
    }
  }

  async function sendWithImage(message, file, dataUrl) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("note", message || "");

    appendMsg({ role: "user", content: message || "(attached an image)", image: dataUrl });
    appendTyping();

    try {
      const res = await fetch(`/api/products/${productId}/diagnose-image`, {
        method: "POST",
        body: fd,
      });
      removeTyping();
      if (!res.ok) {
        appendMsg({ role: "assistant", content: `(error ${res.status}) ${await res.text()}` });
        return;
      }
      const data = await res.json();
      // Push BOTH the user's intent AND what the model saw into history,
      // so subsequent text turns can reason about the image.
      const userHist = `[image attached] ${message || "(no note)"}`;
      const replyText = (data.visible ? `What I see in the image: ${data.visible}\n\n` : "") + (data.reply || "");
      history.push({ role: "user", content: userHist });
      history.push({ role: "assistant", content: replyText });
      appendMsg({ role: "assistant", content: replyText, mode: data.mode, citations: data.citations });
    } catch (e) {
      removeTyping();
      appendMsg({ role: "assistant", content: `(network error) ${e.message}` });
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text && !pendingFile) return;
    input.value = "";

    if (pendingFile) {
      const f = pendingFile, du = pendingDataUrl;
      clearAttachment();
      await sendWithImage(text, f, du);
    } else {
      await sendTextOnly(text);
    }
  });

  resetBtn.addEventListener("click", () => {
    history = [];
    messagesEl.innerHTML = "";
    clearAttachment();
  });
})();
