import { SparkleIcon, GoogleIcon } from './icons.jsx'

export default function GeneratedReview({
  review,
  onReviewChange,
  onRegenerate,
  onPostGoogle,
  onBack,
  loading,
  error,
  postStatus,
  googleConfigured,
}) {
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
          onClick={onPostGoogle}
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

      <div className="post-status" role="status" aria-live="polite">
        {postStatus === 'copied' && (
          <>
            <p className="post-status__title">
              <span aria-hidden="true">✓</span> Your review has been copied!
            </p>
            <p className="post-status__text">Google is opening...</p>
            <p className="post-status__text">Tap the review box and paste your review.</p>
          </>
        )}
        {postStatus === 'manual' && (
          <p className="post-status__text">
            Google is opening. Please copy your review manually if needed.
          </p>
        )}
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
