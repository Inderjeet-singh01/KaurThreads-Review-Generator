# Kaur Threads Boutique — AI Review Generator

## Live deployment

- **Frontend:** https://kaurthreads-review-generator.onrender.com/
- **Backend:** https://kaurthreads-ai-review-generator.onrender.com/

A minimal FastAPI backend that generates a natural-sounding Google review draft
from a star rating and an optional customer experience. The generated text is
only a **draft** for the customer to edit and post themselves.

## What it does

- Exposes one application endpoint, `POST /generate-review`, plus `GET /health`.
- Uses Groq (model `openai/gpt-oss-120b`) to write one review that matches the
  chosen star rating and uses **only** the details the customer provides — it
  never invents products, staff, prices, discounts, services, or events.
- Tone by rating: 1–2 stars negative but respectful, 3 stars neutral, 4–5
  stars positive.

### How the review reaches Google

The backend **does not** and **cannot** post reviews to Google — Google's
policies require the customer to submit their own review. The flow is:

1. Customer selects a rating and generates a review via `POST /generate-review`.
2. Customer edits the draft in the (future) frontend.
3. Customer clicks **"Post on Google"**.
4. The frontend opens Kaur Threads' Google review page (`GOOGLE_REVIEW_URL`).
5. **The customer submits the review themselves on Google's interface.**

`GOOGLE_REVIEW_URL` is configured here as the single source of truth; no OAuth
and no Google API posting is involved.

## Environment variables

| Variable             | Required | Description                                                                 |
| -------------------- | -------- | --------------------------------------------------------------------------- |
| `GROQ_API_KEY`       | Yes      | Groq API key (reused from the Review Reply AI project). Never hardcode it.   |
| `GROQ_MODEL`         | No       | Groq model. Defaults to `openai/gpt-oss-120b`.                              |
| `GOOGLE_REVIEW_URL`  | Yes*     | Public "write a review" URL the frontend opens for the customer.            |
| `CORS_ALLOW_ORIGINS` | No       | Comma-separated browser origins allowed to call the API (future frontend).  |

\* Not required for the API to start, but needed for the end-to-end review flow.
Build the URL from the Google Place ID:
`https://search.google.com/local/writereview?placeid=YOUR_PLACE_ID`

Copy `.env.example` to `.env` and fill in the values. `.env` is gitignored.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in GROQ_API_KEY and GOOGLE_REVIEW_URL
uvicorn app.main:app --reload
```

Interactive docs at `http://127.0.0.1:8000/docs`.

## API

### `POST /generate-review`

Request:

```json
{
  "rating": 5,
  "experience": "Loved the collection and the staff was very helpful"
}
```

- `rating` — integer, 1–5 (required).
- `experience` — string, optional, max 1000 characters.

Response:

```json
{
  "rating": 5,
  "review": "I loved the collection and the staff was very helpful."
}
```

Optional header: `Idempotency-Key` (8–64 letters, digits or `-`). The
frontend sends one per click and resends it when it retries; a repeat that
arrives while the first run is still going (or within 2 minutes of its
success) gets that run's review instead of a new LLM call.

Errors have the body `{"detail": "<customer-safe text>", "code": "...",
"retryable": true|false}` (plus `retry_after` and a `Retry-After` header on
`429`/`503`). Internal error text is only written to the logs.

- `400` `not_boutique` — the experience is about something other than the boutique.
- `409` `review_rejected` — the generated reviews failed a local check
  (invented detail, wrong tone, dropped point, or too close to an earlier
  review), after one fresh retry. The customer can press Regenerate.
- `422` — invalid input (rating out of 1–5, or experience too long).
- `429` `ai_busy` — Groq (and the Gemini fallback, if configured) is rate
  limiting. A short Groq wait (≤4s) is waited out once by the backend;
  otherwise `Retry-After` says how long to wait. Not retried automatically.
- `503` `ai_unavailable` — temporary LLM failure (timeout, network, 5xx,
  empty reply) after the fallback. Safe to retry.
- `502` `ai_error` — permanent LLM failure (missing/invalid key, bad request,
  unknown model). Retrying won't help; check the logs.
- `500` `internal_error` — a bug; the traceback is in the logs.

A request makes at most **two** provider calls (see `app/ai/groq_client.py`)
and no LLM-based checking. A word-length band and style notes are picked locally for
that call; the result is then checked locally for grounding (no garments,
staff, prices, delivery etc. the customer didn't mention), rating tone, and
uniqueness against earlier accepted reviews.

Accepted reviews are stored in SQLite at `REVIEW_HISTORY_PATH` (default
`data/review_history.sqlite3`). On a host with an ephemeral disk (e.g. Render
without a persistent disk) this history resets on each deploy/restart.

### `GET /health`

Returns `{"status": "ok"}` (also answers `HEAD`). It does no LLM, database
or other I/O, so it responds instantly once the process is up. Use it as the
Render **Health Check Path**. It does not keep a Render Free instance awake:
Free instances still sleep after 15 minutes without traffic.

## Render cold starts

On Render Free the backend sleeps when idle, and the first request after
that waits while Render starts it again (often 30–60s). The frontend
handles this (see `frontend/src/api.js`):

1. On page load it pings `/health`, so the backend starts waking while the
   customer picks a rating.
2. On Generate, if the backend hasn't answered in the last 5 minutes, it
   waits for `/health` first ("Connecting to AI service…", then "Starting AI
   service…" if slow): 20s per attempt, 2s/4s/8s backoff, 75s at most.
3. It then calls `/generate-review` (30s timeout) and retries only
   transient failures: network errors, timeouts and 502/503/504 from
   Render's proxy up to twice, a backend `503` once, with 2s/4s backoff and
   the same `Idempotency-Key`. `400`, `409`, `422`, `429` and our `502`/`500`
   are never retried.

The Render logs show `Backend ready: startup took …s` for each boot and a
`Review generation request started / completed / failed … took=…s` line
per request (never the customer's text).

## Tests

```bash
python -m pytest
```

## Frontend

A React + Vite frontend lives in [`frontend/`](frontend/). It is the
customer-facing single page: pick a rating, optionally add a few words, generate
a review draft, edit it, and open Google to post it.

```bash
cd frontend
npm install
cp .env.example .env   # set VITE_API_BASE_URL and VITE_GOOGLE_REVIEW_URL
npm run dev            # http://localhost:5173
```

It calls `POST /generate-review` at `VITE_API_BASE_URL`. **Post on Google**
copies the review and opens `VITE_GOOGLE_REVIEW_URL` so the customer can paste
and submit it on Google. It never posts to Google itself. The dev server
origins (`5173`/`4173`) are already in the backend `CORS_ALLOW_ORIGINS` default. See [`frontend/README.md`](frontend/README.md).
