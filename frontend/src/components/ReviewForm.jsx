import RatingSelector from './RatingSelector.jsx'
import { SparkleIcon, ArrowRightIcon } from './icons.jsx'

const MAX_CHARS = 300

export default function ReviewForm({
  rating,
  onRatingChange,
  experience,
  onExperienceChange,
  onGenerate,
  loading,
  error,
}) {
  function handleTextChange(event) {
    // Hard-limit to MAX_CHARS characters.
    onExperienceChange(event.target.value.slice(0, MAX_CHARS))
  }

  return (
    <form
      className="review-form"
      onSubmit={(e) => {
        e.preventDefault()
        onGenerate()
      }}
      noValidate
    >
      <h2 className="card__title">Select Your Rating</h2>

      <RatingSelector rating={rating} onChange={onRatingChange} disabled={loading} />

      <div className="field">
        <label className="field__label" htmlFor="experience">
          Tell us a little more <span className="field__optional">(optional)</span>
        </label>
        <div className="textarea-wrap">
          <textarea
            id="experience"
            className="textarea"
            placeholder="e.g. Loved the collection, staff was very helpful, great quality..."
            value={experience}
            onChange={handleTextChange}
            maxLength={MAX_CHARS}
            rows={4}
            disabled={loading}
          />
          <span className="char-count" aria-live="polite">
            {experience.length}/{MAX_CHARS}
          </span>
        </div>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <button type="submit" className="btn btn--primary btn--block" disabled={loading}>
        {loading ? (
          <>
            <span className="spinner" aria-hidden="true" />
            Generating your review...
          </>
        ) : (
          <>
            <SparkleIcon width="20" height="20" />
            Generate My Review
            <ArrowRightIcon width="20" height="20" />
          </>
        )}
      </button>
    </form>
  )
}
