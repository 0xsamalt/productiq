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
      speakReply(data.reply);
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
        speakReply(reply);
      } catch (e) {
        removeTyping();
        appendMsg({ role: "assistant", content: `(network error) ${e.message}` });
      }
      imageForm.reset();
    });
  }

  // ---------------------------------------------------------------------------
  // Voice: spoken replies (TTS) + voice input (Web Speech API, Whisper fallback)
  // English only for now.
  // ---------------------------------------------------------------------------
  const micBtn = document.getElementById("mic-btn");
  const speakToggle = document.getElementById("speak-toggle");
  const speakIcon = document.getElementById("speak-icon");

  // --- Text-to-speech (spoken replies) ---
  const tts = window.speechSynthesis || null;
  let speakOn = false;

  function speakReply(text) {
    if (!speakOn || !tts || !text) return;
    // Strip the leading visual labels so they aren't read aloud.
    const clean = text.replace(/^\s*(ASK|DIAGNOSE)\s*[:\-]?\s*/i, "").trim();
    tts.cancel(); // never overlap utterances
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = "en-US";
    u.rate = 1.0;
    tts.speak(u);
  }

  if (speakToggle) {
    if (!tts) {
      speakToggle.disabled = true;
      speakToggle.title = "Speech synthesis not supported in this browser";
      speakToggle.classList.add("opacity-40", "cursor-not-allowed");
    } else {
      speakToggle.addEventListener("click", () => {
        speakOn = !speakOn;
        speakToggle.setAttribute("aria-pressed", String(speakOn));
        speakIcon.textContent = speakOn ? "🔊" : "🔇";
        speakToggle.classList.toggle("text-brand", speakOn);
        if (!speakOn) tts.cancel();
      });
    }
  }

  // --- Speech-to-text (voice input) ---
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let listening = false;

  function setMicState(on) {
    listening = on;
    if (!micBtn) return;
    micBtn.textContent = on ? "⏹️" : "🎤";
    micBtn.classList.toggle("text-red-600", on);
    micBtn.classList.toggle("border-red-400", on);
    micBtn.classList.toggle("animate-pulse", on);
    micBtn.title = on ? "Stop listening" : "Speak your issue";
  }

  // Path A — native Web Speech API (Chrome/Edge): instant, no server round-trip.
  function startWebSpeech() {
    const rec = new SpeechRecognition();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = false;

    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      input.value = (finalText + interim).trim();
    };
    rec.onerror = () => setMicState(false);
    rec.onend = () => {
      setMicState(false);
      const text = input.value.trim();
      if (text) { input.value = ""; sendText(text); }
    };

    setMicState(true);
    rec.start();
    // Allow tapping the mic again to stop early.
    micBtn.onclick = () => { rec.stop(); micBtn.onclick = onMicClick; };
  }

  // Path B — MediaRecorder + server-side Whisper (Firefox/Safari/others).
  let mediaRecorder = null;
  let chunks = [];

  async function startWhisper() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      appendMsg({ role: "assistant", content: "(microphone access was denied)" });
      return;
    }
    chunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      setMicState(false);
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
      if (!blob.size) return;
      const prevPlaceholder = input.placeholder;
      input.placeholder = "transcribing…";
      try {
        const fd = new FormData();
        fd.append("file", blob, "speech.webm");
        const res = await fetch("/api/transcribe", { method: "POST", body: fd });
        input.placeholder = prevPlaceholder;
        if (!res.ok) {
          appendMsg({ role: "assistant", content: `(transcription error ${res.status})` });
          return;
        }
        const { text } = await res.json();
        if (text) sendText(text);
        else appendMsg({ role: "assistant", content: "(couldn't catch that — try again)" });
      } catch (e) {
        input.placeholder = prevPlaceholder;
        appendMsg({ role: "assistant", content: `(network error) ${e.message}` });
      }
    };
    setMicState(true);
    mediaRecorder.start();
    micBtn.onclick = () => { mediaRecorder.stop(); micBtn.onclick = onMicClick; };
  }

  function onMicClick() {
    if (listening) return;
    if (SpeechRecognition) startWebSpeech();
    else if (navigator.mediaDevices && window.MediaRecorder) startWhisper();
    else appendMsg({ role: "assistant", content: "(voice input isn't supported in this browser)" });
  }

  if (micBtn) micBtn.onclick = onMicClick;

  // Stop any speech when the conversation is reset.
  if (resetBtn) resetBtn.addEventListener("click", () => { if (tts) tts.cancel(); });
})();
