// Thin client for the Kaur Threads backend: POST /generate-review, plus
// GET /health to wake the backend up. Configuration comes from Vite env
// variables so no URLs are hardcoded.
//
// The backend runs on Render, which puts an idle instance to sleep. The
// first request after that waits while Render starts it again (often
// 30-60s). So:
//   1. The page pings /health as soon as it loads, to start that wake-up
//      while the customer is still choosing a rating.
//   2. Before generating, we wait until /health answers (bounded), showing
//      "Starting AI service..." if it is slow.
//   3. The generate call itself retries only transient failures (network,
//      timeout, temporary 5xx), a limited number of times with backoff, and
//      reuses one Idempotency-Key so a retry never starts a second review.

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

// Customer-facing messages. We deliberately never surface backend error
// text, status codes, or stack traces to the customer.
export const GENERIC_ERROR =
  'Something went wrong while generating your review. Please try again.'

export const UNAVAILABLE_ERROR =
  'The AI service is temporarily unavailable. Please try again in a few seconds.'

// Shown when the backend answers 429 (the AI service is busy). Not retried
// automatically: the Generate button waits out Retry-After instead.
export const BUSY_ERROR =
  'The AI service is temporarily busy. Please wait a few seconds and try again.'

// Shown when the backend answers 400: the experience isn't about the boutique.
export const OFF_TOPIC_ERROR =
  'Please tell us about your experience with our clothes or services.'

// Shown when the backend answers 409: the drafts it wrote didn't pass its
// checks (e.g. too close to an earlier review). The customer can try again.
export const RETRY_ERROR =
  "We couldn't write a fresh review this time. Please try again."

export const VALIDATION_ERROR =
  'Please check your rating and message, then try again.'

// --- Timing -----------------------------------------------------------------

// One /health attempt. Render holds the request open while the instance
// starts, so a single attempt usually covers most of a cold start.
const HEALTH_TIMEOUT_MS = 20000
// Give up waking the backend after this long (Render cold starts are
// typically under a minute).
const WAKE_BUDGET_MS = 75000
// /health hasn't answered after this long: the backend is starting up.
const SLOW_WAKE_MS = 2500
// A backend that answered this recently is considered awake (Render Free
// sleeps after 15 minutes without traffic).
const AWAKE_FOR_MS = 5 * 60 * 1000
// One generate attempt. The backend caps its own LLM work at ~18s.
const GENERATE_TIMEOUT_MS = 30000
// Waits before retry 1 and retry 2.
const BACKOFF_MS = [2000, 4000]
const MAX_RETRY_WAIT_MS = 8000
// Retries per kind of failure. An LLM outage already cost the backend two
// provider calls, so it gets one retry; transport failures get two.
const MAX_RETRIES = { network: 2, timeout: 1, unavailable: 1 }

/** An error whose message is safe to show the customer. */
export class ApiError extends Error {
  constructor(message, { retryAfter = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.retryAfter = retryAfter // seconds, on 429
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } catch (err) {
    // Distinguish our timeout from other network failures.
    if (timedOut) {
      const timeout = new Error(`Request timed out after ${timeoutMs}ms`)
      timeout.name = 'TimeoutError'
      throw timeout
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

// --- Wake-up / readiness ------------------------------------------------------

let lastAwakeAt = 0
let wakePromise = null
let wakeStartedAt = 0

function markAwake() {
  lastAwakeAt = Date.now()
}

async function pollHealth() {
  const started = Date.now()
  for (let attempt = 0; ; attempt++) {
    const remaining = WAKE_BUDGET_MS - (Date.now() - started)
    if (remaining <= 0) break
    try {
      const res = await fetchWithTimeout(
        `${API_BASE_URL}/health`,
        { method: 'GET', cache: 'no-store' },
        Math.min(HEALTH_TIMEOUT_MS, remaining),
      )
      // Any non-5xx answer means our app is up (even a 404 from an older
      // deploy without /health). 5xx is Render's proxy while it starts.
      if (res.status < 500) {
        markAwake()
        return
      }
      console.warn(`Backend not ready yet (health status ${res.status})`)
    } catch (err) {
      // Network error / timeout: typical while Render starts the instance.
      console.warn('Backend not ready yet:', err?.name || err)
    }
    const delay = Math.min(BACKOFF_MS[0] * 2 ** attempt, MAX_RETRY_WAIT_MS)
    if (Date.now() - started + delay >= WAKE_BUDGET_MS) break
    await sleep(delay)
  }
  console.error(`Backend did not become ready within ${WAKE_BUDGET_MS / 1000}s`)
  throw new ApiError(UNAVAILABLE_ERROR)
}

/**
 * Resolve once the backend answers /health (immediately if it answered
 * recently). Concurrent callers share one wake-up, so this never sends
 * parallel pings.
 *
 * @param {Object} [hooks]
 * @param {() => void} [hooks.onConnecting] Called when a check is needed.
 * @param {() => void} [hooks.onSlow]       Called if the backend is slow to answer (cold start).
 */
export function ensureBackendAwake({ onConnecting, onSlow } = {}) {
  if (!API_BASE_URL) return Promise.resolve()
  if (Date.now() - lastAwakeAt < AWAKE_FOR_MS) return Promise.resolve()
  if (!wakePromise) {
    wakeStartedAt = Date.now()
    wakePromise = pollHealth().finally(() => {
      wakePromise = null
    })
  }
  onConnecting?.()
  const slowTimer = onSlow
    ? setTimeout(onSlow, Math.max(0, SLOW_WAKE_MS - (Date.now() - wakeStartedAt)))
    : null
  return wakePromise.finally(() => clearTimeout(slowTimer))
}

/** Fire-and-forget wake-up on page load. Never throws. */
export function warmUpBackend() {
  ensureBackendAwake().catch(() => {})
}

// --- Generate -----------------------------------------------------------------

function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

function parseRetryAfter(res, data) {
  const value = Number(data?.retry_after ?? res.headers.get('Retry-After'))
  return Number.isFinite(value) && value > 0 ? value : null
}

/**
 * What to do with a non-2xx response: { kind } to retry, { message } to stop.
 * Only transient failures get a kind.
 */
async function classifyResponse(res) {
  let data = null
  try {
    data = await res.json()
  } catch {
    // Not our JSON: e.g. an HTML error page from Render's proxy.
  }
  const retryAfter = parseRetryAfter(res, data)
  const ours = typeof data?.code === 'string'
  switch (res.status) {
    case 400:
      return { message: OFF_TOPIC_ERROR }
    case 409:
      return { message: RETRY_ERROR }
    case 422:
      return { message: VALIDATION_ERROR }
    case 429:
      return { message: BUSY_ERROR, retryAfter }
    case 502:
    case 504:
      // Our 502 means retrying won't help; the proxy's means the instance
      // isn't reachable right now.
      return ours ? { message: UNAVAILABLE_ERROR } : { kind: 'network', retryAfter }
    case 503:
      return ours && data.retryable === false
        ? { message: UNAVAILABLE_ERROR }
        : { kind: ours ? 'unavailable' : 'network', retryAfter }
    default:
      return { message: GENERIC_ERROR }
  }
}

async function readReview(res) {
  let data
  try {
    data = await res.json()
  } catch (err) {
    console.error('generate-review returned invalid JSON:', err)
    throw new ApiError(GENERIC_ERROR)
  }
  if (!data || typeof data.review !== 'string' || !data.review.trim()) {
    console.error('generate-review returned an unexpected shape:', data)
    throw new ApiError(GENERIC_ERROR)
  }
  return data.review.trim()
}

/**
 * Call POST /generate-review, waking the backend first if needed.
 *
 * @param {Object} params
 * @param {number} params.rating       Selected star rating, 1-5.
 * @param {string} [params.experience] Optional free-text experience.
 * @param {(status: 'connecting'|'waking'|'generating'|'retrying') => void} [params.onStatus]
 * @returns {Promise<string>} The generated review text.
 * @throws {ApiError} With a customer-safe message on any failure.
 */
export async function generateReview({ rating, experience, onStatus }) {
  if (!API_BASE_URL) {
    // Misconfiguration — log for the developer, show the generic message.
    console.error('VITE_API_BASE_URL is not set. Configure it in the .env file.')
    throw new ApiError(GENERIC_ERROR)
  }

  const body = JSON.stringify({
    rating,
    experience: experience?.trim() ? experience.trim() : null,
  })
  // One key per click: retries of this click reuse the backend's run.
  const idempotencyKey = newIdempotencyKey()
  const retries = { network: 0, timeout: 0, unavailable: 0 }

  for (let attempt = 0; ; attempt++) {
    await ensureBackendAwake({
      onConnecting: () => onStatus?.('connecting'),
      onSlow: () => onStatus?.('waking'),
    })
    onStatus?.(attempt === 0 ? 'generating' : 'retrying')

    let failure
    try {
      const res = await fetchWithTimeout(
        `${API_BASE_URL}/generate-review`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
          body,
        },
        GENERATE_TIMEOUT_MS,
      )
      if (res.ok) {
        markAwake()
        return await readReview(res)
      }
      failure = await classifyResponse(res)
      if (failure.kind !== 'network') markAwake() // our app answered
    } catch (err) {
      if (err instanceof ApiError) throw err
      // Network failure or timeout. The instance may have gone back to
      // sleep or restarted: check readiness again before retrying.
      failure = { kind: err?.name === 'TimeoutError' ? 'timeout' : 'network' }
      console.warn(`generate-review attempt ${attempt + 1} failed:`, err?.name || err)
    }

    if (failure.kind === 'network') lastAwakeAt = 0
    if (!failure.kind || retries[failure.kind] >= MAX_RETRIES[failure.kind]) {
      if (failure.kind) console.error(`generate-review gave up after ${attempt + 1} attempts (${failure.kind})`)
      throw new ApiError(failure.message || UNAVAILABLE_ERROR, { retryAfter: failure.retryAfter })
    }
    retries[failure.kind]++
    const backoff = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
    const delay = Math.min(Math.max(backoff, (failure.retryAfter || 0) * 1000), MAX_RETRY_WAIT_MS)
    console.warn(`generate-review retrying (${failure.kind}) in ${delay}ms`)
    onStatus?.('retrying')
    await sleep(delay)
  }
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
