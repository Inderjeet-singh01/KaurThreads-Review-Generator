import { useEffect, useRef, useState } from 'react'
import Header from './components/Header.jsx'
import Hero from './components/Hero.jsx'
import ReviewForm from './components/ReviewForm.jsx'
import GeneratedReview from './components/GeneratedReview.jsx'
import ClosingSection from './components/ClosingSection.jsx'
import ContactLinks from './components/ContactLinks.jsx'
import { generateReview, GENERIC_ERROR, GOOGLE_REVIEW_URL, warmUpBackend } from './api.js'
import { copyText } from './clipboard.js'
import { googleReviewLink } from './googleReview.js'

const NO_RATING_ERROR = 'Please select a rating first.'
const EMPTY_REVIEW_ERROR = 'Please generate or write your review first.'
const MAX_COOLDOWN_SECONDS = 30

export default function App() {
  const [rating, setRating] = useState(0)
  const [experience, setExperience] = useState('') // customer's own words (source)
  const [review, setReview] = useState('') // generated + editable draft
  const [phase, setPhase] = useState('form') // 'form' | 'result'
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [postStatus, setPostStatus] = useState(null) // 'copied' | 'manual' | null
  // 'connecting' | 'waking' | 'generating' | 'retrying' while loading,
  // 'success' after a review arrives, '' otherwise.
  const [status, setStatus] = useState('')
  // After a 429, Generate stays disabled for the backend's Retry-After.
  const [cooldown, setCooldown] = useState(0) // seconds left

  const googleConfigured = Boolean(GOOGLE_REVIEW_URL)
  const googleLink = googleReviewLink()
  // Set synchronously so a fast double click can't send a second request
  // before the disabled button re-renders: one click, one POST.
  const generatingRef = useRef(false)

  // Wake the backend (Render may have put it to sleep) while the customer
  // is still choosing a rating, so Generate is usually instant.
  useEffect(() => {
    warmUpBackend()
  }, [])

  useEffect(() => {
    if (cooldown <= 0) return undefined
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  async function runGenerate() {
    if (generatingRef.current || cooldown > 0) return
    if (!rating) {
      setError(NO_RATING_ERROR)
      return
    }
    generatingRef.current = true
    setError('')
    setPostStatus(null)
    setStatus('generating')
    setLoading(true)
    try {
      const text = await generateReview({ rating, experience, onStatus: setStatus })
      setReview(text)
      setPhase('result')
      setStatus('success')
    } catch (err) {
      setStatus('')
      setError(err?.message || GENERIC_ERROR)
      if (err?.retryAfter) setCooldown(Math.min(Math.ceil(err.retryAfter), MAX_COOLDOWN_SECONDS))
    } finally {
      generatingRef.current = false
      setLoading(false)
    }
  }

  function handleRatingChange(value) {
    setRating(value)
    if (error === NO_RATING_ERROR) setError('')
  }

  function handleReviewChange(value) {
    setReview(value)
    if (status === 'success') setStatus('')
    if (error === EMPTY_REVIEW_ERROR) setError('')
  }

  // Runs on the "Post on Google" link's click. The link itself opens Google:
  // a real tap on a link is what lets phones hand it to the Maps app or open
  // it in the browser straight on the review box, and it is never treated as
  // a popup. So this handler stays synchronous and only cancels the
  // navigation when there is nothing to post.
  function handlePostGoogle(event) {
    const text = review.trim() // current (possibly edited) review
    if (!text) {
      event.preventDefault()
      setPostStatus(null)
      setError(EMPTY_REVIEW_ERROR)
      return
    }
    setError('')

    // Google's review box can't be pre-filled, so copy the text for the
    // customer to paste. Best-effort — never block opening Google.
    if (copyText(text)) {
      setPostStatus('copied')
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(
        () => setPostStatus('copied'),
        (err) => {
          console.warn('Could not copy review to clipboard:', err)
          setPostStatus('manual')
        },
      )
    } else {
      setPostStatus('manual')
    }
  }

  function handleBack() {
    setPhase('form')
    setStatus('')
    setError('')
    setPostStatus(null)
  }

  return (
    <div className="page" id="top">
      <Header />

      <main className="content">
        <Hero />

        <div className="review-panel">
          {phase === 'form' ? (
            <ReviewForm
              rating={rating}
              onRatingChange={handleRatingChange}
              experience={experience}
              onExperienceChange={setExperience}
              onGenerate={runGenerate}
              loading={loading}
              status={status}
              cooldown={cooldown}
              error={error}
            />
          ) : (
            <div className="card">
              <GeneratedReview
                review={review}
                onReviewChange={handleReviewChange}
                onRegenerate={runGenerate}
                onPostGoogle={handlePostGoogle}
                onBack={handleBack}
                loading={loading}
                status={status}
                cooldown={cooldown}
                error={error}
                postStatus={postStatus}
                googleConfigured={googleConfigured}
                googleLink={googleLink}
              />
            </div>
          )}

          <ContactLinks />
        </div>

        <ClosingSection />
      </main>
    </div>
  )
}
