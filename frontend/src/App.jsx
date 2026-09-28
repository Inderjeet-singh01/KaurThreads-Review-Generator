import { useState } from 'react'
import Header from './components/Header.jsx'
import Hero from './components/Hero.jsx'
import Benefits from './components/Benefits.jsx'
import ReviewForm from './components/ReviewForm.jsx'
import GeneratedReview from './components/GeneratedReview.jsx'
import FeatureStrip from './components/FeatureStrip.jsx'
import ClosingSection from './components/ClosingSection.jsx'
import Footer from './components/Footer.jsx'
import { generateReview, GENERIC_ERROR, GOOGLE_MAPS_URL } from './api.js'

const NO_RATING_ERROR = 'Please select a rating first.'
const EMPTY_REVIEW_ERROR = 'Please generate or write your review before posting on Google.'

export default function App() {
  const [rating, setRating] = useState(0)
  const [experience, setExperience] = useState('') // customer's own words (source)
  const [review, setReview] = useState('') // generated + editable draft
  const [phase, setPhase] = useState('form') // 'form' | 'result'
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [postMessage, setPostMessage] = useState('') // Post on Google status

  const googleConfigured = Boolean(GOOGLE_MAPS_URL)

  async function runGenerate() {
    if (!rating) {
      setError(NO_RATING_ERROR)
      return
    }
    setError('')
    setPostMessage('')
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
      setPostMessage('')
      setError(EMPTY_REVIEW_ERROR)
      return
    }
    if (!googleConfigured) return
    setError('')

    // Google can't be pre-filled, so copy the text for the customer to paste.
    // Best-effort — never block opening Google Maps.
    try {
      await navigator.clipboard.writeText(text)
      setPostMessage(
        'Your review has been copied. Open Google Maps and paste it into your review.'
      )
    } catch (err) {
      console.warn('Could not copy review to clipboard:', err)
      setPostMessage('Google Maps is opening. Please copy your review manually.')
    }

    // Same-tab navigation (no popup) so the OS/browser can hand the Universal
    // URL to the Google Maps app when installed, or open it on the web.
    window.location.href = GOOGLE_MAPS_URL
  }

  function handleBack() {
    setPhase('form')
    setError('')
    setPostMessage('')
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
              postMessage={postMessage}
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
