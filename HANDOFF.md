# MANTIS — Team Handoff

> Last sync: this doc reflects branch `mantis-mvp` (PR #1).
> Maintainer: the person who scaffolded this should keep the table below in sync as features land.

---

## 1. What this is

A product-support platform where companies list products and users get a **technician-style diagnostic assistant** per product, grounded in the manufacturer's official manuals.

The assistant is **not a search bar**. It runs the brief's 8-step protocol: understand → identify causes from docs → ask one elimination question → evaluate response → narrow → diagnose with citation → recommend next action.

## 2. Architecture (one-pager)

```
                ┌────────────────────────────────────────────────┐
   Browser ───▶ │ FastAPI  (backend/app/main.py)                 │
                │  ├─ routes/pages.py     server-rendered Jinja  │
                │  ├─ routes/products.py  company + product CRUD │
                │  ├─ routes/upload.py    PDF/text → chunks      │
                │  ├─ routes/diagnose.py  text chat              │
                │  └─ routes/image.py     multimodal chat        │
                └──────────────┬─────────────────┬───────────────┘
                               │                 │
                  ┌────────────▼───┐    ┌────────▼──────────────┐
                  │ Moss runtime    │    │ HF Inference (Gemma 3 │
                  │ (in-process)    │    │ 27B-IT, text+vision)   │
                  │ ONE shared      │    │ via huggingface_hub    │
                  │ index           │    │ InferenceClient        │
                  │ per-product     │    │                        │
                  │ scoped by       │    │                        │
                  │ metadata filter │    │                        │
                  └────────────────┘    └────────────────────────┘
                               ▲
                ┌──────────────┴───────────────┐
                │ SQLite (productiq.db)        │
                │  companies / products / docs │
                └──────────────────────────────┘
```

**Key design decisions** (don't undo these without discussion):

- **One Moss index for the whole app.** Per-product isolation is enforced by stamping `product_id` on every chunk's metadata and adding `{field:"product_id", condition:{"$eq":<id>}}` to every query filter. Why: Moss free tier caps at 3 indexes; one shared index scales to any number of products.
- **System prompt is universal, not per-product.** Product-specific facts come from Moss-retrieved chunks injected into each user message. See `diagnostic_agent.py:SYSTEM_PROMPT`. Don't put product names or part numbers in the system prompt.
- **Chunking is ours, retrieval is Moss.** `pdf_parser.py` does sliding-window chunking (1200 chars / 200 overlap), Moss does embedding + similarity search.
- **Plain JS chat, no framework.** `static/chat.js` keeps history client-side and POSTs each turn to `/api/products/<id>/diagnose`.

## 3. Quick start

```bash
cd backend
cp .env.example .env       # then fill in MOSS_PROJECT_ID, MOSS_PROJECT_KEY, HF_TOKEN
bash run.sh                # creates conda env productiq (py3.11), installs deps, launches uvicorn :8000
```

`HF_TOKEN` must be a **fine-grained** token with **"Make calls to Inference Providers"** enabled, otherwise Gemma calls return 403.

`MOSS_PROJECT_ID` / `_KEY` come from the project dashboard at moss.dev (free tier).

To wipe and reset Moss + local DB:
```bash
python cleanup_moss.py     # deletes legacy indexes, ensures the shared one
rm -f productiq.db          # local SQLite
```

## 4. Feature status

Legend: ✅ done · 🟡 partial · ❌ not started

| Area | Sub-feature | Status | File / endpoint | Notes |
|---|---|---|---|---|
| **Marketplace** | Browse all products | ✅ | `routes/pages.py:index` · `templates/index.html` | Grid of all products |
| | Product detail page | ✅ | `routes/pages.py:product_page` · `templates/product.html` | |
| | **Search box** | ❌ | TODO `templates/index.html` + route filter | Easy: add `?q=` filter to the index route |
| **Companies** | Create company | ✅ | `POST /api/companies` | Email-only, no real auth |
| | Company dashboard | ✅ | `templates/company_detail.html` | Add product / upload / delete |
| | Auth (real login) | ❌ | TODO | Currently anyone can claim any email |
| **Knowledge repo** | Upload PDF | ✅ | `POST /api/products/{id}/upload` | Parsed + chunked + indexed |
| | Upload text / .md | ✅ | same | |
| | Upload image (as asset) | 🟡 | same | Stored on disk, NOT chunked / indexed |
| | **Index uploaded image OCR** | ❌ | TODO `pdf_parser.py` + Gemma vision | Use Gemma to extract text from images of manuals |
| | Attach external link | 🟡 | `POST /api/products/{id}/upload-link` | URL stored, NOT fetched / chunked. Needs HTML fetcher → text → Moss |
| | **Doc list on product page** | 🟡 | `templates/product.html:30-35` literally says "listing endpoint TBD" | Trivial: pass docs into template like `company_detail.html` does |
| | Download docs | ❌ | TODO add `GET /api/products/{id}/docs/{doc_id}` | Use `storage_path` on `Document` |
| **Diagnostic assistant** | ASK / DIAGNOSE state machine | ✅ | `diagnostic_agent.py` | Mode prefix `[ASK]`/`[DIAGNOSE]` |
| | Inline manual citations | ✅ | `diagnostic_agent.py` + `static/chat.js` | Pills under each assistant reply |
| | Safety override (fire, smoke, shock) | ✅ | `SYSTEM_PROMPT` "SAFETY" block | Auto-escalates to "contact a technician" |
| | No-docs fallback | ✅ | `SYSTEM_PROMPT` hard rule | Canonical line, no hallucination |
| | Streaming tokens | ❌ | TODO | Currently single-shot per turn (~1-3s). Switch to `llm_service.chat_stream` + SSE |
| | Conversation persistence | ❌ | History lives in browser memory; refresh = reset | Add a `Conversation` table if needed |
| **Image troubleshooting** | Upload image of issue | ✅ | `POST /api/products/{id}/diagnose-image` | Two-call pattern: see → retrieve → diagnose |
| | Combines vision + retrieval | ✅ | `routes/image.py` | |
| **Bonus tracks (none started)** | | | | |
| | Voice input | ❌ | | Pipecat/LiveKit + STT/TTS. Templates exist in `../moss/apps/pipecat-moss/` but need API keys |
| | Video timestamp guidance | ❌ | | Needs Whisper for transcript → Moss indexes timestamped chunks |
| | Maintenance schedules (manual define) | ❌ | | New DB table `MaintenanceTask{product_id, title, every_n_days}` + cron-ish reminders |
| | Auto-extract maintenance from docs | ❌ | | Single Gemma call over each uploaded PDF asking for JSON list of `{task, interval}` |
| | "My products" inventory + reminders | ❌ | | Needs end-user accounts (real auth blocker) |
| | Spare part suggestions | ❌ | | Could piggyback on the diagnostic agent — extra system instruction |
| | Multi-language Q&A | 🟡 essentially-free | none | Gemma 3 already supports 140 languages. Users typing in Hindi/Tamil get Hindi/Tamil answers. Just needs UI labels translated. |
| | Warranty / recall alerts | ❌ | | DB + notification path |
| | Product health analytics | ❌ | | Aggregate over `Conversation` rows (don't exist yet) |
| | Visual guidance (flowcharts) | ❌ | | Out of scope for backend; needs Mermaid renderer in chat reply |

## 5. Recommended next features (priority order, with effort)

| Priority | Feature | Effort | Why |
|---|---|---|---|
| P0 | Doc list on product page | 15 min | Trivial, already-collected data; closes obvious UX gap |
| P0 | Marketplace search box | 30 min | Brief explicitly asks for "browse and search". 1 input + `LIKE %q%` SQL |
| P1 | Index uploaded image manuals via Gemma OCR | 1 h | Many real-world manuals are scanned PDFs / photos |
| P1 | External link indexing (fetch URL → extract text → Moss) | 1-2 h | `httpx.get` + `BeautifulSoup`. YouTube → transcript via `youtube-transcript-api` |
| P1 | Auto-extract maintenance tasks from PDF | 1-2 h | One Gemma JSON-mode call per uploaded PDF; surface tasks for company approval |
| P1 | "Suggested questions" / "Common issues" panel on product page | 1 h | Pre-prompt Gemma over the indexed docs to generate 3-5 starter questions |
| P2 | Streaming chat tokens (SSE) | 1-2 h | UX polish; replies start appearing in 200ms |
| P2 | Maintenance schedules + reminders | 3-4 h | Needs `MaintenanceTask` model + a list view; reminders can be email-stub for demo |
| P2 | Conversation persistence | 1 h | Adds analytics later; required for any "support trends" feature |
| P3 | Real auth (passwordless email link) | 4-6 h | Unblocks "my products inventory" and per-user features |
| P3 | Voice input via Pipecat | half-day | High demo wow-factor but needs Deepgram/Cartesia keys |

## 6. Where to add code (by feature)

| Adding... | Touch these files |
|---|---|
| A new model / DB table | `app/models.py` (define SQLModel) — schema auto-creates on next boot via `init_db()` |
| A new route | New file in `app/routes/`, then add `app.include_router(...)` in `main.py` |
| A new ingestion source | Extend `app/pdf_parser.py` or add `app/<source>_parser.py`; call `moss_service.add_chunks(product_id, chunks)` |
| New UI page | New `app/templates/<page>.html` extending `base.html`; add route in `app/routes/pages.py` |
| Changing the diagnostic protocol | `app/diagnostic_agent.py:SYSTEM_PROMPT` — keep it universal (no product-specific content) |
| New LLM call shape (e.g. JSON mode, tools) | `app/llm_service.py` — add a new helper alongside `chat` / `chat_stream` / `chat_with_image` |

## 7. Known issues / footguns

- **Moss native lib segfaults on Python exit.** Cosmetic — happens after the request is served. If `uvicorn --reload` becomes noisy, drop `--reload` in `run.sh`.
- **No real auth.** Anyone can register as any company. Don't deploy publicly; fine for the demo.
- **`.env` lives at `backend/.env`, gitignored.** Never `git add -A`; always stage files explicitly. `git check-ignore -v backend/.env` should print a hit.
- **Inference Providers cost real money** (small — pennies per chat turn). HF dashboard → Billing.
- **HF token must be Fine-grained with the Inference Providers scope.** "Read"-only tokens 403.
- **Gemma 3 12B is NOT on HF Inference Providers** as of writing. We use 27B which is strictly more capable. Don't switch back without verifying.
- **Chunking is character-windowed.** Tables and code blocks get fragmented. Not a blocker for the demo, but if retrieval quality suffers on a complex manual, upgrade to a heading-aware splitter.

## 8. Demo checklist

For a clean demo, seed with one realistic product before the judges see it:

1. Register a company ("Hero MotoCorp" or similar).
2. Add a product with category + description.
3. Upload a real-world manual PDF (e.g. a 10-page scooter service manual).
4. Open the public product page and run these scripts:
   - Normal: "the horn isn't working" → ASK → answer about headlight → DIAGNOSE with citation.
   - Image: photo of a dashboard warning light → "what does this mean?"
   - Safety: "I smell something burning" → immediate safe-stop directive.
   - Off-topic: "how do I file my taxes?" → canonical no-docs fallback.

All four behaviors are verified working at the time of this writeup.
