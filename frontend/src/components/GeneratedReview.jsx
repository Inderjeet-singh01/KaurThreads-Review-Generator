import { SparkleIcon, GoogleIcon } from './icons.jsx'
import { STATUS_HINTS, STATUS_LABELS, SUCCESS_MESSAGE, cooldownLabel } from '../status.js'

// While regenerating, the button reads "Regenerating..." instead of the
// form's "Generating your review...".
const REGENERATE_LABELS = { ...STATUS_LABELS, generating: 'Regenerating...' }

export default function GeneratedReview({
  review,
  onReviewChange,
  onRegenerate,
  onPostGoogle,
  onBack,
  loading,
  status,
  cooldown,
  error,
  postStatus,
  googleConfigured,
  googleLink,
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

      <p className="form-status" role="status" aria-live="polite">
        {loading ? STATUS_HINTS[status] : status === 'success' && !error ? SUCCESS_MESSAGE : null}
      </p>

      <div className="generated__actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onRegenerate}
          disabled={loading || cooldown > 0}
          aria-busy={loading}
        >
          {loading ? (
            <>
              <span className="spinner spinner--dark" aria-hidden="true" />
              {REGENERATE_LABELS[status] || REGENERATE_LABELS.generating}
            </>
          ) : cooldown > 0 ? (
            cooldownLabel(cooldown)
          ) : (
            <>
              <SparkleIcon width="18" height="18" />
              Regenerate Review
            </>
          )}
        </button>

        {googleConfigured && !loading ? (
          // The click copies the review and shows the "what to do next" guide
          // instead of navigating; the guide's own link opens Google (see
          // App.jsx). The href stays so the button is still a real link.
          <a
            className="btn btn--primary"
            href={googleLink.href}
            target={googleLink.target}
            rel="noopener noreferrer"
            onClick={onPostGoogle}
            title="Copy your review and open Google"
          >
            <GoogleIcon width="20" height="20" />
            Post on Google
          </a>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            disabled
            title={
              googleConfigured
                ? 'Please wait for your review'
                : 'Google review link is not configured yet'
            }
          >
            <GoogleIcon width="20" height="20" />
            Post on Google
          </button>
        )}
      </div>

      <div className="post-status" role="status" aria-live="polite">
        {postStatus === 'copied' && (
          <>
            <p className="post-status__title">
              <span aria-hidden="true">✓</span> Your review has been copied!
            </p>
            <p className="post-status__text">
              Google opens on the review box. Pick your stars, tap the box and paste your review.
            </p>
          </>
        )}
        {postStatus === 'manual' && (
          <p className="post-status__text">
            Google opens on the review box. Copy your review above and paste it there.
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
