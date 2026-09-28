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

export default function App() {
  const [rating, setRating] = useState(0)
  const [experience, setExperience] = useState('') // customer's own words (source)
  const [review, setReview] = useState('') // generated + editable draft
  const [phase, setPhase] = useState('form') // 'form' | 'result'
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const googleConfigured = Boolean(GOOGLE_REVIEW_URL)

  async function runGenerate() {
    if (!rating) {
      setError(NO_RATING_ERROR)
      return
    }
    setError('')
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

  function handlePostGoogle() {
    if (!googleConfigured) return
    window.open(GOOGLE_REVIEW_URL, '_blank', 'noopener,noreferrer')
  }

  function handleBack() {
    setPhase('form')
    setError('')
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
              onReviewChange={setReview}
              onRegenerate={runGenerate}
              onPostGoogle={handlePostGoogle}
              onBack={handleBack}
              loading={loading}
              error={error}
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
