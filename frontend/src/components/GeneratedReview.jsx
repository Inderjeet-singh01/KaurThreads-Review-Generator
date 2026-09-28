import { SparkleIcon, GoogleIcon } from './icons.jsx'

export default function GeneratedReview({
  review,
  onReviewChange,
  onRegenerate,
  onPostGoogle,
  onBack,
  loading,
  error,
  googleConfigured,
}) {
  async function handlePost() {
    // Copy the edited text so the customer can paste it on Google (Google's
    // page cannot be pre-filled). Best-effort — never block the redirect.
    try {
      if (navigator.clipboard && review.trim()) {
        await navigator.clipboard.writeText(review.trim())
      }
    } catch {
      /* clipboard unavailable — the customer can still copy manually */
    }
    onPostGoogle()
  }

  return (
    <div className="generated">
      <div className="generated__head">
        <h2 className="card__title">Your Review</h2>
        <button type="button" className="link-btn" onClick={onBack} disabled={loading}>
          Edit details
        </button>
      </div>

      <p className="generated__hint">
        Review it, make any edits you like, then post it on Google.
      </p>

      <label className="sr-only" htmlFor="generated-review">
        Your generated review
      </label>
      <textarea
        id="generated-review"
        className="textarea textarea--review"
        value={review}
        onChange={(e) => onReviewChange(e.target.value)}
        rows={6}
        disabled={loading}
      />

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <div className="generated__actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onRegenerate}
          disabled={loading}
        >
          {loading ? (
            <>
              <span className="spinner spinner--dark" aria-hidden="true" />
              Regenerating...
            </>
          ) : (
            <>
              <SparkleIcon width="18" height="18" />
              Regenerate Review
            </>
          )}
        </button>

        <button
          type="button"
          className="btn btn--primary"
          onClick={handlePost}
          disabled={loading || !googleConfigured}
          title={
            googleConfigured
              ? 'Copy your review and open Google'
              : 'Google review link is not configured yet'
          }
        >
          <GoogleIcon width="20" height="20" />
          Post on Google
        </button>
      </div>

      {!googleConfigured && (
        <p className="form-note" role="note">
          The Google review link isn’t configured yet. Set VITE_GOOGLE_REVIEW_URL
          to enable posting.
        </p>
      )}
    </div>
  )
}
