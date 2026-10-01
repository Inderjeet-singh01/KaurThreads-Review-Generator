import { useEffect, useRef } from 'react'
import { CheckIcon, GoogleIcon } from './icons.jsx'

const STEPS = [
  { title: 'Tap the stars', text: 'Choose your rating on Google.' },
  { title: 'Paste your review', text: 'Tap the review box, then choose Paste.' },
  { title: 'Tap Post', text: 'That’s it, thank you!' },
]

// Full-screen "what to do next" sheet shown when the customer taps
// "Post on Google". Google's review box can't be pre-filled, so this makes
// sure they know the review is on their clipboard and needs pasting.
//
// - copied: shown for `delay` ms with a progress bar, then the app opens
//   Google. The "Open Google Reviews" link stays as a real-tap fallback in
//   case the browser blocked the scripted open.
// - manual: copying failed, so nothing opens on its own; the review is shown
//   to copy by hand before the customer taps the link.
export default function PostGuide({ status, redirected, delay, review, googleLink, onOpen, onClose }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    dialogRef.current?.focus()
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    function handleKey(event) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => {
      document.body.style.overflow = overflow
      document.removeEventListener('keydown', handleKey)
    }
  }, [onClose])

  const copied = status === 'copied'
  const counting = copied && !redirected

  return (
    <div className="post-guide">
      <div
        ref={dialogRef}
        className="post-guide__sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="post-guide-title"
        aria-describedby="post-guide-lead"
        tabIndex={-1}
      >
        <span className={`post-guide__badge${copied ? '' : ' post-guide__badge--warn'}`} aria-hidden="true">
          {copied ? <CheckIcon width="30" height="30" /> : '!'}
        </span>

        <h2 id="post-guide-title" className="post-guide__title">
          {copied ? 'Review copied!' : 'Copy your review first'}
        </h2>
        <p id="post-guide-lead" className="post-guide__lead">
          {copied
            ? 'Google Reviews is opening next. Here’s what to do there:'
            : 'We couldn’t copy it automatically. Press and hold the text below, choose Select All, then Copy.'}
        </p>

        {!copied && (
          <textarea
            className="textarea post-guide__review"
            value={review}
            readOnly
            rows={4}
            aria-label="Your review"
            onFocus={(e) => e.target.select()}
          />
        )}

        <ol className="post-guide__steps">
          {STEPS.map((step, i) => (
            <li key={step.title} className="post-guide__step">
              <span className="post-guide__num" aria-hidden="true">
                {i + 1}
              </span>
              <span>
                <strong>{step.title}</strong>
                <span className="post-guide__step-text">{step.text}</span>
              </span>
            </li>
          ))}
        </ol>

        {counting && (
          <div className="post-guide__progress" role="status">
            <span className="post-guide__bar" style={{ animationDuration: `${delay}ms` }} />
            <span className="post-guide__progress-label">Opening Google Reviews…</span>
          </div>
        )}

        <div className="post-guide__actions">
          {redirected && <p className="post-guide__retry">Google didn’t open?</p>}
          <a
            className="btn btn--primary"
            href={googleLink.href}
            target={googleLink.target}
            rel="noopener noreferrer"
            onClick={onOpen}
          >
            <GoogleIcon width="20" height="20" />
            {counting ? 'Open now' : 'Open Google Reviews'}
          </a>
          <button type="button" className="link-btn post-guide__close" onClick={onClose}>
            {counting ? 'Cancel' : 'Done'}
          </button>
        </div>
      </div>
    </div>
  )
}
