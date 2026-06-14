// Diagnostic chat. Plain fetch + DOM; no framework.
(function () {
  const productId = window.MANTIS_PRODUCT_ID;
  const messagesEl = document.getElementById("messages");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const resetBtn = document.getElementById("reset-btn");
  const imageForm = document.getElementById("image-form");

  let history = []; // [{role, content}]

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

    bubble.innerHTML = `${imgHTML}<div>${badge}<span>${escapeHtml(content)}</span></div>${citationsHTML(citations)}`;
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

  async function sendText(message) {
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

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    await sendText(text);
  });

  resetBtn.addEventListener("click", () => {
    history = [];
    messagesEl.innerHTML = "";
  });

  if (imageForm) {
    imageForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(imageForm);
      const file = fd.get("file");
      const note = fd.get("note") || "";
      if (!file || !file.size) return;

      const dataUrl = await new Promise(r => {
        const reader = new FileReader();
        reader.onload = () => r(reader.result);
        reader.readAsDataURL(file);
      });
      appendMsg({ role: "user", content: note || "(uploaded an image)", image: dataUrl });
      history.push({ role: "user", content: `[uploaded an image] ${note}` });
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
        const reply = (data.visible ? `What I see in the image: ${data.visible}\n\n` : "") + data.reply;
        history.push({ role: "assistant", content: reply });
        appendMsg({ role: "assistant", content: reply, mode: data.mode, citations: data.citations });
      } catch (e) {
        removeTyping();
        appendMsg({ role: "assistant", content: `(network error) ${e.message}` });
      }
      imageForm.reset();
    });
  }
})();
