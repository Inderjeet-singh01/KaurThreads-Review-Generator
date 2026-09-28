import { useState } from 'react'
import { StarIcon } from './icons.jsx'

const RATINGS = [
  { value: 1, label: 'Poor' },
  { value: 2, label: 'Fair' },
  { value: 3, label: 'Good' },
  { value: 4, label: 'Very Good' },
  { value: 5, label: 'Excellent' },
]

/**
 * Interactive 5-star selector implemented as a radiogroup for accessibility.
 * Arrow keys move the selection; a star is "on" when it is <= the active value
 * (selected, or hovered/focused for preview).
 */
export default function RatingSelector({ rating, onChange, disabled }) {
  const [hover, setHover] = useState(0)
  const active = hover || rating

  function handleKeyDown(event) {
    if (disabled) return
    const current = rating || 0
    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
      event.preventDefault()
      onChange(Math.min(5, current + 1))
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
      event.preventDefault()
      onChange(Math.max(1, current - 1))
    }
  }

  return (
    <div
      className="rating"
      role="radiogroup"
      aria-label="Select your rating from 1 to 5 stars"
      onKeyDown={handleKeyDown}
      onMouseLeave={() => setHover(0)}
    >
      {RATINGS.map(({ value, label }) => {
        const on = value <= active
        const selected = value === rating
        return (
          <button
            type="button"
            key={value}
            className={`rating__item${on ? ' is-on' : ''}`}
            role="radio"
            aria-checked={selected}
            aria-label={`${value} ${label}`}
            tabIndex={selected || (!rating && value === 1) ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(value)}
            onMouseEnter={() => setHover(value)}
            onFocus={() => setHover(value)}
            onBlur={() => setHover(0)}
          >
            <StarIcon className="rating__star" filled={on} width="44" height="44" />
            <span className="rating__value">{value}</span>
            <span className="rating__label">{label}</span>
          </button>
        )
      })}
    </div>
  )
}
