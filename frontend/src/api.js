// Thin client for the Kaur Threads backend. The only route it talks to is
// POST /generate-review. Configuration comes from Vite env variables so no
// URLs are hardcoded.

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

// A friendly message shown to customers for any failure. We deliberately never
// surface backend error text, status codes, or stack traces to the customer.
export const GENERIC_ERROR =
  'Something went wrong while generating your review. Please try again.'

// Shown when the backend answers 429 (the AI service is busy). Not retried.
export const BUSY_ERROR =
  'Lots of reviews are being written right now. Please wait a moment and try again.'

/**
 * Call POST /generate-review.
 *
 * @param {Object} params
 * @param {number} params.rating       Selected star rating, 1-5.
 * @param {string} [params.experience] Optional free-text experience.
 * @param {number} [params.timeoutMs]  Abort after this many ms (default 20s).
 * @returns {Promise<string>} The generated review text.
 * @throws {Error} With a customer-safe message on any failure.
 */
export async function generateReview({ rating, experience, timeoutMs = 20000 }) {
  if (!API_BASE_URL) {
    // Misconfiguration — log for the developer, show the generic message.
    console.error('VITE_API_BASE_URL is not set. Configure it in the .env file.')
    throw new Error(GENERIC_ERROR)
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  let response
  try {
    response = await fetch(`${API_BASE_URL}/generate-review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rating,
        experience: experience?.trim() ? experience.trim() : null,
      }),
      signal: controller.signal,
    })
  } catch (err) {
    // Network failure or timeout (abort).
    console.error('generate-review request failed:', err)
    throw new Error(GENERIC_ERROR)
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    console.error('generate-review responded with status', response.status)
    throw new Error(response.status === 429 ? BUSY_ERROR : GENERIC_ERROR)
  }

  let data
  try {
    data = await response.json()
  } catch (err) {
    console.error('generate-review returned invalid JSON:', err)
    throw new Error(GENERIC_ERROR)
  }

  if (!data || typeof data.review !== 'string' || !data.review.trim()) {
    console.error('generate-review returned an unexpected shape:', data)
    throw new Error(GENERIC_ERROR)
  }

  return data.review.trim()
}

// Google Business Profile "Ask for reviews" link (https://g.page/r/<id>/review).
// It is the only link Google maintains for opening the stars + review box
// directly on Android, iOS and desktop, in the Maps app or the browser.
// Without the trailing /review it opens the place page, so add it if missing.
function toReviewUrl(value) {
  const url = (value || '').trim()
  const shortLink = url.match(/^(https:\/\/g\.page\/r\/[^/?#]+)\/?$/)
  return shortLink ? `${shortLink[1]}/review` : url
}

export const GOOGLE_REVIEW_URL = toReviewUrl(import.meta.env.VITE_GOOGLE_REVIEW_URL)
