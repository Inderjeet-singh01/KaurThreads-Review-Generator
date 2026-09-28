import { useState } from 'react'
import { BotanicalSprig } from './icons.jsx'

/**
 * Hero portrait — the South Asian model in the pink embroidered outfit from the
 * reference design. This is a MAJOR visual element and must be the exact source
 * image, not a substitute.
 *
 * To use the real asset: drop the file at `public/hero-portrait.jpg` (or .png /
 * .webp and adjust HERO_IMAGE below). No other change is needed — it loads
 * automatically and keeps the arched crop, position, and dimensions.
 * Until the asset is present a tasteful, clearly-labelled placeholder is shown
 * so nothing is silently faked.
 */
const HERO_IMAGE = '/hero-portrait.jpg'

export default function Hero() {
  const [hasImage, setHasImage] = useState(true)

  return (
    <section className="hero">
      <BotanicalSprig className="hero__sprig hero__sprig--left" />
      <BotanicalSprig className="hero__sprig hero__sprig--mid" />

      <div className="hero__text">
        <p className="hero__eyebrow">Your Opinion Matters</p>
        <h1 className="hero__title">
          Share Your
          <br />
          Experience
        </h1>
        <p className="hero__subtitle">
          Your feedback means a lot <br className="hero__break" />
          and helps us serve you better.
        </p>
      </div>

      <div className="hero__media">
        <span className="hero__halo" aria-hidden="true" />
        <div className="hero__portrait">
          {hasImage ? (
            <img
              className="hero__img"
              src={HERO_IMAGE}
              alt="Kaur Threads customer in a pink embroidered outfit"
              width="1127"
              height="1396"
              onError={() => setHasImage(false)}
            />
          ) : (
            <div
              className="hero__placeholder"
              role="img"
              aria-label="Boutique model portrait (add public/hero-portrait.jpg)"
            >
              <img src="/lotus.svg" alt="" width="48" height="38" />
              <span>Add public/hero-portrait.jpg</span>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
