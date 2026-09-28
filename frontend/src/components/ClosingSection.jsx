import { useState } from 'react'
import { BotanicalSprig, HeartIcon } from './icons.jsx'

/**
 * Bottom blush section with the handwritten "Your Feedback Inspires Us" and the
 * boutique clothing-rack photo from the reference.
 *
 * To use the real asset: drop the file at `public/boutique-rack.jpg` (or adjust
 * RACK_IMAGE). It loads automatically and keeps the exact crop. Until then a
 * clearly-labelled placeholder is shown so nothing is silently substituted.
 */
const RACK_IMAGE = '/boutique-rack.jpg'

export default function ClosingSection() {
  const [hasImage, setHasImage] = useState(true)

  return (
    <section className="closing" aria-label="Your feedback inspires us">
      <BotanicalSprig className="closing__sprig" />

      <p className="closing__script" aria-hidden="true">
        <span className="closing__line closing__line--1">Your</span>
        <span className="closing__line closing__line--2">Feedback</span>
        <span className="closing__line closing__line--3">Inspires Us</span>
        <HeartIcon className="closing__heart" />
      </p>
      <span className="sr-only">Your feedback inspires us.</span>

      <div className="closing__media">
        {hasImage ? (
          <img
            className="closing__img"
            src={RACK_IMAGE}
            alt="Kaur Threads boutique clothing collection on display"
            width="1536"
            height="1024"
            loading="lazy"
            onError={() => setHasImage(false)}
          />
        ) : (
          <div
            className="closing__placeholder"
            role="img"
            aria-label="Boutique interior (add public/boutique-rack.jpg)"
          >
            <img src="/lotus.svg" alt="" width="48" height="38" />
            <span>Add public/boutique-rack.jpg</span>
          </div>
        )}
      </div>
    </section>
  )
}
