# Kaur Threads Boutique — Review Generator (Frontend)

Customer-facing single page built with **React + Vite**. Customers pick a star
rating, optionally add a few words, generate an AI review draft, edit it, and
post it on Google in one click.

## Setup

```bash
npm install
cp .env.example .env    # fill in the two variables below
npm run dev             # http://localhost:5173
```

Build for production:

```bash
npm run build           # outputs to dist/
npm run preview         # serve the production build locally
```

## Environment variables

Both are **required** and must never be hardcoded in source.

| Variable                 | Description                                                                 |
| ------------------------ | --------------------------------------------------------------------------- |
| `VITE_API_BASE_URL`      | Base URL of the FastAPI backend (no trailing slash), e.g. `http://127.0.0.1:8000`. |
| `VITE_GOOGLE_REVIEW_URL` | Google "write a review" link, e.g. `https://search.google.com/local/writereview?placeid=ChIJXfSGFKDvDzkRaANBXxmg1Z8`. |

## How it connects to the backend

- One request only: `POST {VITE_API_BASE_URL}/generate-review` with body
  `{ "rating": <1-5>, "experience": <string|null> }`.
- Uses the `review` field of the JSON response as the editable draft.
- Handles loading, network/timeout (20s abort), non-2xx, and invalid responses
  with a single customer-safe message — backend error details are never shown.
- **Post on Google** copies the current (edited) text to the clipboard (best
  effort), shows a confirmation, and ~700ms later opens `VITE_GOOGLE_REVIEW_URL`
  in the same tab. The customer pastes and submits the review on Google; the
  app never posts to Google and adds no backend route.

## Adding a real boutique photo

Drop a photo at `public/boutique.jpg`. It loads automatically; until then a
tasteful placeholder is shown. See
[`src/components/BoutiqueImage.jsx`](src/components/BoutiqueImage.jsx).

## Structure

```
src/
├── App.jsx              # state + phase (form → result)
├── api.js               # POST /generate-review client
├── styles.css           # premium cream/green/gold design system
└── components/
    ├── Header.jsx  Hero.jsx  Benefits.jsx
    ├── RatingSelector.jsx    # accessible 5-star radiogroup
    ├── ReviewForm.jsx  GeneratedReview.jsx
    ├── FeatureStrip.jsx  BoutiqueImage.jsx  Footer.jsx
    └── icons.jsx
```
