# Kaur Threads Boutique — AI Review Generator

A minimal FastAPI backend that generates a natural-sounding Google review draft
from a star rating and an optional customer experience. The generated text is
only a **draft** for the customer to edit and post themselves.

## What it does

- Exposes a single endpoint: `POST /generate-review`.
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

Errors:

- `422` — invalid input (rating out of 1–5, or experience too long).
- `502` — the LLM call failed or returned nothing.

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

It calls `POST /generate-review` at `VITE_API_BASE_URL` and opens
`VITE_GOOGLE_REVIEW_URL` for the customer to submit on Google. It never posts to
Google itself. The dev server origins (`5173`/`4173`) are already in the backend
`CORS_ALLOW_ORIGINS` default. See [`frontend/README.md`](frontend/README.md).
