# ProductIQ — Assistant for Your Products

> *"The information already exists. The problem is access."*
> — Hackathon brief

ProductIQ is a per-product diagnostic platform. Manufacturers list their products and upload the manuals (PDF, text, scanned pages, support URLs, YouTube tutorials). End users get an assistant that behaves like a **service technician**, not a chatbot — it asks elimination questions, narrows the cause, and answers with citations back to the source page or video timestamp.

Built on **Moss** (sub-10ms in-process semantic search) and **Gemma 3 27B** (text + vision, multilingual) via HuggingFace Inference.

---

## 1. The two-sided platform

| Role | Where they work | What they do |
|---|---|---|
| **Company** | `/company/<id>` dashboard | Register, list products, upload manuals (PDF / text / images / external links / YouTube), see chunk counts per doc, delete products, **read a per-product Health Score** — top issues, documentation gaps & trends mined from real diagnostic chats |
| **End user** | `/` marketplace → `/p/<id>` | **Search the marketplace by name or category**, browse product cards, chat with the diagnostic assistant in any language, upload photos of faults, **view + download every manual** the manufacturer attached, **resume a previous conversation** (chat history persists across browser refreshes), listen to spoken replies |

Both sides use the same Moss-backed knowledge base — the company **builds** it, the user **queries** it.

### Marketplace search

The `/` page has a real search box (icon-prefixed input + Search / Clear buttons). It filters products by `name` or `category` via a `?q=` query parameter using a `LIKE %q%` SQL match — results refresh server-side with the result count shown. Empty-state messaging adapts to whether the user is exploring vs. coming up empty on a specific search.

### Manuals: view + download for end users

The public product page (`/p/<id>`) lists every doc the manufacturer attached — PDFs, text/markdown, images, external links, YouTube videos — with:

- A **kind badge** (`pdf` / `text` / `image` / `link` / `video`) for instant scanning
- **Download button** (`GET /api/products/{id}/docs/{doc_id}`) that streams the original file from disk — for PDFs, images, and text uploads, the user gets the actual file the company uploaded
- **Open ↗** link for external URLs (HTML pages, YouTube videos) — opens in a new tab, deep-links into the source
- **Chunk count** on every indexed doc — so the user can see how much grounding material exists per source

This satisfies the brief's *"Users can browse and download these materials from the product page"* requirement explicitly.

---

## 2. Architecture

```
                    ┌──────────────────────────────────────────────┐
   Browser ──HTTPS─▶│ FastAPI  (server-rendered Jinja + vanilla JS) │
                    │  ├─ routes/pages.py       marketplace / dashboard
                    │  ├─ routes/products.py    company + product CRUD + download
                    │  ├─ routes/upload.py      PDF / text / image / link / video ingestion
                    │  ├─ routes/diagnose.py    text chat (multilingual)
                    │  ├─ routes/image.py       multimodal vision-aware diagnosis
                    │  ├─ routes/audio.py       voice input (Whisper STT)
                    │  └─ routes/health.py      product health score + issue insights
                    └──────┬──────────────────────┬────────────────┘
                           │                      │
              ┌────────────▼────────┐   ┌─────────▼─────────────────┐
              │ Moss runtime         │  │ HF Inference                │
              │ (sub-10ms in-process │  │ • Gemma 3 27B (text+vision) │
              │  semantic search)    │  │ • Whisper (STT fallback)    │
              │ ONE shared index,    │  │                              │
              │ product_id metadata  │  │                              │
              │ filter per product   │  │                              │
              └──────────────────────┘  └─────────────────────────────┘
                           ▲
              ┌────────────┴───────────────┐
              │ SQLite (productiq.db)       │
              │ companies / products / docs │
              │ + session-scoped chat log   │
              └─────────────────────────────┘
```

### Three design decisions that make this work

**One shared Moss index with product-scoped retrieval.**
Every chunk carries a `product_id` in metadata; every query attaches `{field:"product_id", condition:{$eq:<id>}}`. One index, infinite products, zero cross-product leakage — and no hitting Moss's free-tier index cap.

**Universal system prompt + per-product *context*.**
The diagnostic protocol (ASK / DIAGNOSE / safety / no-fabrication) lives in one system prompt that never changes. Product-specific facts (manual chunks, product name, description) are injected into each user message at call time. Companies don't write prompts; one prompt evolves, and product knowledge stays in the docs where it belongs.

**Our chunker, Moss's retrieval.**
We parse PDFs / pages / images / transcripts into structured, citation-friendly chunks; Moss handles embedding, similarity, and metadata filtering. Clean separation, both layers stay swappable.

---

## 3. The diagnostic assistant — the differentiator

The brief says it must behave "like a mechanic, technician, or support engineer." Our agent runs the brief's 8-step protocol explicitly:

| Brief step | What the agent does | How |
|---|---|---|
| 1. Understand symptoms + context | History + product info + user message go in | `diagnose()` in `diagnostic_agent.py` |
| 2. Identify possible causes from docs | `top_k=6` retrieval from Moss with `product_id` filter | `moss_service.query()` |
| 3. Ask follow-ups to eliminate | `[ASK]` mode with **ONE** elimination question per turn | System prompt rule (A) |
| 4. Suggest safe inspection steps | Inspection must be performable powered-off; safety override blocks dangerous proposals | System prompt SAFETY block |
| 5. Evaluate user responses | Full conversation passed back each turn | History appended to messages |
| 6. Narrow down root causes | ASK→DIAGNOSE state machine | Mode prefix parsed from reply |
| 7. Recommend corrective actions | `[DIAGNOSE]` mode emits "next concrete action" | System prompt rule (B) |
| 8. Provide supporting references | Inline citation in reply + structured `citations[]` rendered as pills | `_format_evidence()` + `citationsHTML()` in `chat.js` |

### Reply modes — visible to the user

- **`[ASK]`** — green left-border bubble + small `ASK` badge. Means: I need one more piece of info to narrow this down. One question, never five.
- **`[DIAGNOSE]`** — amber left-border bubble + `DIAGNOSE` badge. Means: based on what we have, here's the likely cause, the cited source, and the next action.

The mode prefix is stripped before display so the user sees a clean message; the UI uses the prefix to colour-code the bubble.

### Extras beyond the brief

**Intent classification (FAULT vs USAGE).** Users ask two distinct things:
- *"My fries are soggy"* — a FAULT, run elimination
- *"Do I need to shake the fries?"* — a USAGE question, answer directly

The system prompt classifies each message and skips the ASK loop for usage questions, answering straight from retrieved chunks with a citation.

**Safety override (auto-detect + safe-stop).** If the message mentions fire, smoke, sparks, burning smell, electrical shock, fuel/gas leak, or unstable mechanical failure, the agent skips inspection steps entirely and immediately tells the user to stop using the product, power it off, and call a qualified technician. Hard rule, overrides everything else. Never instructs the user to bypass interlocks, defeat guards, open sealed batteries, or work on live mains.

**Anti-fabrication.** Hard rule: never invent concrete numbers (times, temperatures, voltages, torque, fuse ratings, part numbers, figure numbers) that don't appear verbatim in retrieved chunks. If the user asks for a specific number and it's missing, the agent says so explicitly instead of borrowing from general world knowledge.

**Canonical no-docs fallback.** If retrieval returns nothing relevant, the agent replies with a fixed sentence directing the user to the manufacturer — no guessing, no fake answers.

**Turn budget.** After three user turns, the agent must commit to a `[DIAGNOSE]` rather than asking forever. Confidence trail is suppressed for confident answers (only mentioned if the agent is genuinely unsure).

**Inline citations + pill rendering.** Every assistant message can carry up to 4 citation pills (source filename, page, optional URL). Hover shows the chunk text. The UI never lies about where information came from.

**Persistent chat memory across sessions.** Every conversation is tied to a browser-scoped `session_id` cookie. Every user message and assistant reply (including image-diagnosis turns) is written to a `ChatMessage` table the moment it's exchanged. On page refresh, the server re-renders the entire history server-side so the chat is *there* before any JavaScript runs — no flicker, no "loading…", no client-side state to lose. A single click on the **Reset** button calls `/api/chat/reset`, which deletes the session's messages from the DB and clears the cookie. Effect: the user can close the tab, walk away, return tomorrow, and pick up the diagnostic thread exactly where they left it.

---

## 4. Product Health Score — insights for the manufacturer

The diagnostic chat isn't only a support tool — it's a continuous stream of real-world failure reports. ProductIQ mines that stream into a per-product **Health Score** so manufacturers can see what's actually breaking, where their documentation falls short, and whether problems are trending up. No reviews, ratings, or ticket forms to fill in — every signal comes from conversations users were already having with the assistant.

### How it's captured

Every `/diagnose` turn writes a `DiagnosticEvent`: the user's reported issue, the resolved mode (`ASK` / `DIAGNOSE`), whether the manuals actually covered it (citations present and no canonical no-docs fallback), and the top retrieval score. Zero extra user effort, zero new UI on the end-user side — the analytics fall out of conversations that already happen.

### The score (0–100)

On demand — the company clicks **Refresh insights** — ProductIQ recomputes a composite score and caches it. Four weighted components:

| Component | Weight | Signal |
|---|---|---|
| **Coverage** | 30% | Share of reported issues the manuals actually answered → exposes documentation gaps |
| **Resolution** | 30% | Share of conversations (per session) that reached a confident `[DIAGNOSE]` |
| **Severity** | 25% | Frequency-weighted severity of issue themes (LLM-labeled high / medium / low) |
| **Trend** | 15% | Last-30-day vs prior-30-day issue volume — rising problems pull the score down |

Below 5 conversations the numeric score is withheld (statistically meaningless) but the raw signals still render. The number maps to a grade: **Excellent** (≥85) · **Good** (≥70) · **Fair** (≥50) · **At risk** (below).

### The insights

Alongside the number, Gemma clusters the raw issue reports into themes — counts and doc-gap rates derived in code, not trusted to the model — and surfaces:

- **Top reported issues** — ranked by frequency, each with a severity pill and an example verbatim report (e.g. *Charging Issues · high · 5×*).
- **Documentation gaps** — issue themes the manuals didn't cover for most reports: exactly what the company should document next.
- **Narrative summary** — a 2-3 sentence health readout written for the manufacturer.

### Where it lives

On the company dashboard (`/company/<id>`), inside each product card: a score badge + grade, four breakdown bars, the ranked issues, and the doc-gap panel. Computed on-demand and cached in a `ProductInsight` row (one per product), so every dashboard load reads it cheaply. `POST /api/products/{id}/insights/refresh` recomputes; `GET /api/products/{id}/insights` reads the cache.

### Graceful degradation

The numeric score and breakdown bars are pure arithmetic over `DiagnosticEvent` rows — they render with no external calls. Only the issue clustering and summary need an LLM call; if it fails, the score still computes from coverage, resolution and trend, with clustering quietly skipped rather than 500-ing the dashboard.

---

## 5. Image diagnosis — multimodal in one model

End users upload a phone photo of their faulty product (dashboard light, burnt fuse, corroded wires, error screen) directly from the chat UI. The flow:

1. **Vision describe** — Gemma 3 27B vision is given the image **plus product context** (name, category, description) and asked to describe what is visible. Crucial: without product context, internal-mechanism photos get misidentified (a mixer-grinder motor base looks like a light fixture). With it, the description is product-aware.
2. **Retrieve** — the description (in English, via the rewriter) is sent to Moss with the `product_id` filter; relevant manual chunks come back.
3. **Diagnose** — the image, the description, the retrieved chunks, and the SYSTEM_PROMPT are sent back to Gemma. Reply follows the full ASK/DIAGNOSE protocol with citations.

The image description is rendered to the user in their own language (Hindi, Spanish, etc.) — same multilingual pipeline as text chat.

No separate OCR, no separate vision model — one Gemma call per step, multimodal native.

---

## 6. Knowledge sources — five flavors, one pipeline

All five funnel into the same shared Moss index with `product_id` metadata. The diagnostic loop doesn't care where a chunk came from — only that it's tagged with the right product.

| Source | Ingestion | Citation rendering |
|---|---|---|
| **PDF manuals** | `pypdf` per-page extraction → section-aware recursive splitter (paragraph → line → sentence → word → char) → 1200-char chunks with 120-char overlap → page + section tagged. **Auto-OCR fallback**: if pypdf returns zero text (scanned / image-only PDF), every page is rendered to PNG via PyMuPDF and OCRed with Gemma 3 vision, then chunked the same way — *any* PDF becomes searchable, even photographed manual scans. | `manual.pdf p.4` |
| **Text / Markdown** | Same chunker, no page dimension | `notes.md` |
| **Images (company-side, e.g. scanned manual pages)** | Gemma 3 27B vision OCR with structured prompt (extract every label / error code / table row) → text → same chunker | `error-chart.png` |
| **External HTML links** (FAQ pages, vendor docs, support portals, Wikipedia, blog posts) | Company pastes a URL in the "…or paste a URL" form. Server does `httpx.get(url)` with a browser-like User-Agent, follows redirects, enforces a 2 MB cap and 30 s timeout. BeautifulSoup strips `<nav>`, `<script>`, `<style>`, `<footer>`, `<aside>`, `<form>`, `<iframe>`. Prefers `<main>` / `<article>` containers when present. Auto-extracts the page `<title>` to use as the source name if the company left the title blank. Cleaned text flows through the same section-aware chunker; every chunk carries the original URL in its metadata so citations can deep-link back. | `Wikipedia — Refrigerator` (clickable) |
| **YouTube videos** | `youtube-transcript-api` pulls auto-captions → grouped into ~60-second windows (or ≤1200 chars) → each chunk tagged with `?t=<seconds>` URL anchor | `Philips airfryer video, 1:01` (clickable, jumps to that second) |

### Section-aware chunking (vs. naive char windows)

Naive sliding windows split mid-sentence and lose section context. Ours:

1. Detect section headings — `Section 4.2`, `4.2 Electrical Fuses`, markdown `#`, or all-caps lines.
2. Group text under each heading.
3. Recursively split each section by paragraph → line → sentence → word → char.
4. **Prepend the heading to every chunk** so the embedding (and the LLM later) sees the context, not just the body.
5. Tight 120-char overlap (~10%) — enough to bridge a sentence split, not enough to waste embedding tokens.

So when a user asks about the horn, the chunk Moss returns reads:
```
[Section 4.2 - Electrical fuses.]
Fuse F3 (10A) protects the horn and indicator circuits...
```
— and the citation pill says `manual.pdf p.4` pointing to that exact section.

---

## 7. Multilingual — works in any of Gemma's 140 languages

A user types in Hindi, Tamil, Spanish, or English — same flow, no extra config:

```
user input    ─▶ Gemma(rewrite)            ─▶ English search phrase
              ─▶ Moss query (English-leaning embedder)
              ─▶ relevant English chunks
              ─▶ Gemma(diagnose) with LANGUAGE directive
              ─▶ reply in user's original language
```

Why the rewrite step: `moss-minilm` (the embedder) is English-leaning. Querying it directly with Hindi works poorly; querying with the English keywords gets clean hits.

Why the LANGUAGE directive in the diagnostic prompt: Gemma alone tends to default to English replies. We pin the output language to the user's input language explicitly. The `[ASK]/[DIAGNOSE]` prefix stays English (the UI parses it); the body switches.

Image-description step uses the same trick — if the user's note alongside the photo is in Hindi, the description comes back in Hindi too.

---

## 8. Voice — input and output

**Voice input** — 🎤 button next to the chat input:
- **Chrome / Edge:** Web Speech API runs in-browser. Instant, no server round-trip, no API cost.
- **Firefox / Safari (no Web Speech):** record via `MediaRecorder`, POST the blob to `/api/transcribe`, server calls HF Whisper, transcript fills the input. Same UX.

**Voice output** — 🔇/🔊 toggle in the chat header:
- Browser `speechSynthesis` reads the agent's reply aloud. The `[ASK]/[DIAGNOSE]` prefix is stripped before speaking.

Hands-free use case from the brief — *"places phone nearby while repairing a scooter, voice guides each step"* — works end-to-end with zero backend cost on Chromium browsers.

---

## 9. UI / UX

Server-rendered Jinja + Tailwind (CDN) + vanilla JS. No frameworks, no build step. The whole interactive surface is one HTML file per page plus one `chat.js`.

- **Marketplace hero** — brand-gradient backdrop, four capability pills (Grounded · Cites · Multimodal · Safety-aware), search box with magnifier icon.
- **Product cards** — hover-lift effect, brand-tinted category badge, "Open assistant →" affordance.
- **Product page** — public, with the chat panel + a "Diagnose by photo" sidebar + the manuals list with Download buttons + clickable links.
- **Company dashboard** — sticky "Add product" form, always-visible per-product manual upload area (drag-friendly), URL/YouTube attach form, doc list with chunk counts.
- **Chat panel** — live status dot ("Grounded in <product>'s manuals · Gemma 3 27B"), animated message-bubble entrance, mode-coloured borders (purple = user, green-left = ASK, amber-left = DIAGNOSE), citation pills under every assistant message.
- **Brand mark** — gradient purple square with `P`, "ProductIQ" wordmark, sticky header with backdrop blur.
- **Static asset cache-busting** (`?v=2`) so JS/CSS reload after each deploy.

---

## 10. Data model

Six SQLModel tables:

```python
Company         id  name  email  created_at
Product         id  company_id  name  category  description  image_url  created_at
Document        id  product_id  filename  kind  url  storage_path  chunk_count  indexed  created_at
ChatMessage     id  session_id  role  content  created_at
DiagnosticEvent id  product_id  session_id  user_message  mode  had_coverage  top_score  created_at
ProductInsight  id  product_id  health_score  grade  breakdown_json  summary  top_issues_json  coverage_gaps_json  trend  sample_size  computed_at
```

- `Document.kind` ∈ `{"pdf", "text", "image", "link", "video"}` — every ingestion path stamps this so the UI can render kind-specific affordances (Download vs Open ↗) and the doc list shows the right metadata (page count, transcript timestamps, link target).
- `ChatMessage` is keyed by a browser-side `session_id` cookie, so chat history persists per device and is restorable on page refresh (rendered server-side on first paint). `/api/chat/reset` deletes the session's rows and clears the cookie in one call.
- `DiagnosticEvent` logs one row per diagnostic turn — the analytics signal behind the Product Health Score (§4). `ProductInsight` caches the computed score + clustered issues per product (one row each), recomputed on demand so the dashboard reads it cheaply.
- Product delete cascades: Moss vectors (by metadata filter) → `Document` rows → storage files → `Product` row, in one route.

---

## 11. Stack — and why each pick

| Layer | Pick | Why |
|---|---|---|
| Web framework | **FastAPI** | Async, fast, OpenAPI-friendly, drops directly into a single uvicorn process |
| Database | **SQLite via SQLModel** | Zero-config for a hackathon; SQLModel = SQLAlchemy + Pydantic in one ORM |
| Retrieval runtime | **Moss** | Sub-10ms in-process semantic search, no remote vector DB hop, metadata filtering with `$eq`/`$and`/`$in`/`$near` |
| LLM | **Gemma 3 27B-IT** (text + vision) via HF Inference Providers | Multimodal in **one** model — no separate vision API, no OCR pipeline. 140-language support gets multilingual for free. Cheap on a hackathon budget. |
| STT (voice fallback) | **Whisper large-v3** via `provider="hf-inference"` | Whisper is the de facto open ASR; HF Inference serves it reliably; only kicks in for browsers without Web Speech. |
| TTS | **Browser `speechSynthesis`** | Zero backend cost, zero latency, works offline. |
| PDF | **pypdf** (text layer) + **PyMuPDF** (page rasterizer) | Pure-Python, no native deps. pypdf reads any normal PDF; PyMuPDF kicks in only for scanned PDFs where pypdf finds no text — those pages get rendered to PNG and OCRed by Gemma vision. |
| HTML | **BeautifulSoup + httpx** | Lightweight; we strip chrome explicitly so retrieval gets clean text. |
| YouTube | **youtube-transcript-api** | Pulls existing captions — no Whisper transcription cost, no API key. |
| Frontend | **Jinja + Tailwind CDN + vanilla JS** | Zero build step, hard-refresh-friendly cache-busting, total page weight ~minimal. |

---

## 12. Running it

```bash
git clone https://github.com/0xsamalt/productiq
cd productiq/backend
bash run.sh        # creates .env from .env.example on first run, prints what to fill in, exits
# (edit backend/.env with MOSS_PROJECT_ID, MOSS_PROJECT_KEY, HF_TOKEN)
bash run.sh        # auto-detects conda (anaconda3 / miniconda3 / miniforge3 / /opt/conda),
                   # creates env productiq (Python 3.11), installs deps, boots uvicorn on :8000
# open http://localhost:8000
```

`run.sh` is portable — it falls back to `python3 -m venv .venv` if no conda is available, and asks `conda env list` for the real env location instead of guessing the path (works on machines with multiple conda installs).

`HF_TOKEN` must be a Fine-grained token with the **"Make calls to Inference Providers"** scope, and either the **"hf-inference"** provider enabled (for Whisper) or any provider that serves `google/gemma-3-27b-it` (Together / Fireworks / Nebius / etc., picked automatically by `provider="auto"`).

---

## 13. The four-line summary

ProductIQ turns every product manual into a **technician** — not a chatbot.

It uses **Moss** for sub-10ms retrieval grounded in the manufacturer's docs, **Gemma 3 27B** as the brain (text + vision + 140 languages), and a single shared index with metadata-scoped queries so the same architecture scales from one product to a catalog of thousands. The diagnostic agent runs an explicit 8-step protocol — ASK to eliminate, DIAGNOSE with citation — and refuses to fabricate numbers, propose dangerous steps, or answer outside its grounded knowledge.

PDFs, text docs, scanned manual pages, external links, and YouTube videos all flow through the same chunking + indexing pipeline; users ask questions in any language, upload photos of faults, or speak hands-free; every answer cites where it came from.

That's the brief, plus the parts the brief didn't ask for.
