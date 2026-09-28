import { useState } from 'react'
import Header from './components/Header.jsx'
import Hero from './components/Hero.jsx'
import Benefits from './components/Benefits.jsx'
import ReviewForm from './components/ReviewForm.jsx'
import GeneratedReview from './components/GeneratedReview.jsx'
import FeatureStrip from './components/FeatureStrip.jsx'
import ClosingSection from './components/ClosingSection.jsx'
import Footer from './components/Footer.jsx'
import { generateReview, GENERIC_ERROR, GOOGLE_REVIEW_URL } from './api.js'

const NO_RATING_ERROR = 'Please select a rating first.'
const EMPTY_REVIEW_ERROR = 'Please generate or write your review first.'
// Long enough for the customer to see the copy confirmation before Google opens.
const REDIRECT_DELAY_MS = 700

export default function App() {
  const [rating, setRating] = useState(0)
  const [experience, setExperience] = useState('') // customer's own words (source)
  const [review, setReview] = useState('') // generated + editable draft
  const [phase, setPhase] = useState('form') // 'form' | 'result'
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [postStatus, setPostStatus] = useState(null) // 'copied' | 'manual' | null

  const googleConfigured = Boolean(GOOGLE_REVIEW_URL)

  async function runGenerate() {
    if (!rating) {
      setError(NO_RATING_ERROR)
      return
    }
    setError('')
    setPostStatus(null)
    setLoading(true)
    try {
      const text = await generateReview({ rating, experience })
      setReview(text)
      setPhase('result')
    } catch (err) {
      setError(err?.message || GENERIC_ERROR)
    } finally {
      setLoading(false)
    }
  }

  function handleRatingChange(value) {
    setRating(value)
    if (error === NO_RATING_ERROR) setError('')
  }

  function handleReviewChange(value) {
    setReview(value)
    if (error === EMPTY_REVIEW_ERROR) setError('')
  }

  async function handlePostGoogle() {
    const text = review.trim() // current (possibly edited) review
    if (!text) {
      setPostStatus(null)
      setError(EMPTY_REVIEW_ERROR)
      return
    }
    if (!googleConfigured) return
    setError('')

    // Google's review box can't be pre-filled, so copy the text for the
    // customer to paste. Best-effort — never block opening Google.
    try {
      await navigator.clipboard.writeText(text)
      setPostStatus('copied')
    } catch (err) {
      console.warn('Could not copy review to clipboard:', err)
      setPostStatus('manual')
    }

    // Let the confirmation render before leaving the page. Same-tab
    // navigation, so no popup blocker is involved.
    setTimeout(() => {
      window.location.href = GOOGLE_REVIEW_URL
    }, REDIRECT_DELAY_MS)
  }

  function handleBack() {
    setPhase('form')
    setError('')
    setPostStatus(null)
  }

  return (
    <div className="page" id="top">
      <Header />

      <main className="content">
        <Hero />
        <Benefits />

        <div className="card">
          {phase === 'form' ? (
            <ReviewForm
              rating={rating}
              onRatingChange={handleRatingChange}
              experience={experience}
              onExperienceChange={setExperience}
              onGenerate={runGenerate}
              loading={loading}
              error={error}
            />
          ) : (
            <GeneratedReview
              review={review}
              onReviewChange={handleReviewChange}
              onRegenerate={runGenerate}
              onPostGoogle={handlePostGoogle}
              onBack={handleBack}
              loading={loading}
              error={error}
              postStatus={postStatus}
              googleConfigured={googleConfigured}
            />
          )}

          <FeatureStrip />
        </div>

        <ClosingSection />
      </main>

      <Footer />
    </div>
  )
}
