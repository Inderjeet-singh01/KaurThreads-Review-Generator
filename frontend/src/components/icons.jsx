// Small inline line-icons. Keeping them here avoids an icon-library dependency.
// Each inherits `currentColor` so CSS controls the color.

export function StarIcon({ filled = false, ...props }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="M12 2.9l2.72 5.52 6.08.88-4.4 4.29 1.04 6.06L12 16.79l-5.44 2.86 1.04-6.06-4.4-4.29 6.08-.88L12 2.9z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth={filled ? 1.8 : 1.15}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function HeartIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M12 20.3s-7.6-4.5-9.4-9.3C1.4 7.7 3.5 4.6 6.8 4.6c2.2 0 3.7 1.3 5.2 3.3 1.5-2 3-3.3 5.2-3.3 3.3 0 5.4 3.1 4.2 6.4-1.8 4.8-9.4 9.3-9.4 9.3z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function DiamondIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M6.5 3.5h11l3.5 5-9 12.5L3 8.5l3.5-5z M3 8.5h18 M9.5 3.5L8 8.5l4 12.5 4-12.5-1.5-5 M6.5 3.5L8 8.5 M17.5 3.5L16 8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function ShieldHeartIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M12 15s-3-1.9-3-4c0-1.2 1-1.8 1.8-1.3.5.3.9.8 1.2 1.3.3-.5.7-1 1.2-1.3.8-.5 1.8.1 1.8 1.3 0 2.1-3 4-3 4z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function PeopleIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <g stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="6.6" r="2.7" />
        <circle cx="5.6" cy="8.2" r="2.2" />
        <circle cx="18.4" cy="8.2" r="2.2" />
        <path d="M7.4 19.5v-2.3c0-2.6 2-4.7 4.6-4.7s4.6 2.1 4.6 4.7v2.3z" />
        <path d="M6.9 12.4a3.6 3.6 0 00-4.4 3.5v2.1h4.9 M17.1 12.4a3.6 3.6 0 014.4 3.5v2.1h-4.9" />
      </g>
    </svg>
  )
}

export function SparkleIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M9.5 4.5c.7 4.6 2.6 6.6 7.2 7.3-4.6.7-6.5 2.7-7.2 7.3-.7-4.6-2.6-6.6-7.2-7.3 4.6-.7 6.5-2.7 7.2-7.3z"
        fill="currentColor"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinejoin="round"
      />
      <path
        d="M18.5 1.5c.4 2.2 1.3 3.1 3.5 3.5-2.2.4-3.1 1.3-3.5 3.5-.4-2.2-1.3-3.1-3.5-3.5 2.2-.4 3.1-1.3 3.5-3.5z"
        fill="currentColor"
      />
    </svg>
  )
}

export function LightningIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M13.6 2.5L5.2 13.4h6.1l-1.2 8.1 8.7-11.3h-6.3l1.1-7.7z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function EditIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <g stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round">
        <path d="M11 4.5H5.5a1.5 1.5 0 00-1.5 1.5v12.5A1.5 1.5 0 005.5 20H18a1.5 1.5 0 001.5-1.5V13" />
        <path d="M18.3 3.3a1.9 1.9 0 012.7 2.7l-8.3 8.3-3.6.9.9-3.6 8.3-8.3z" />
        <path d="M16.6 5l2.7 2.7" />
      </g>
    </svg>
  )
}

export function CheckIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M5 12.5l4.5 4.5L19 7.5"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function ClipboardIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <g stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round">
        <path d="M8.5 4.5H6.5A1.5 1.5 0 005 6v13.5A1.5 1.5 0 006.5 21h11a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5h-2" />
        <rect x="8.5" y="3" width="7" height="3.5" rx="1" />
        <path d="M8.5 11.5h7 M8.5 15h4.5" />
      </g>
    </svg>
  )
}

export function ArrowRightIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M3 12h17.5 M14.5 6l6 6-6 6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function ChevronRightIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M9.5 5.5l6.5 6.5-6.5 6.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function PhoneIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M21 16.4v2.8a1.9 1.9 0 01-2.07 1.9 18.8 18.8 0 01-8.2-2.92 18.5 18.5 0 01-5.7-5.7A18.8 18.8 0 012.1 4.24 1.9 1.9 0 013.99 2.2H6.8a1.9 1.9 0 011.9 1.63c.12.9.34 1.78.66 2.63a1.9 1.9 0 01-.43 2L7.73 9.67a15.2 15.2 0 005.7 5.7l1.2-1.2a1.9 1.9 0 012-.43c.85.32 1.73.54 2.63.66A1.9 1.9 0 0121 16.4z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// Instagram glyph in its brand gradient — used only as a recognizable link icon.
// `mono` draws it as a quiet line icon in `currentColor` instead.
export function InstagramIcon({ mono = false, ...props }) {
  const paint = mono ? 'currentColor' : 'url(#ig-gradient)'
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      {!mono && (
        <defs>
          <linearGradient id="ig-gradient" x1="3" y1="21" x2="21" y2="3" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#f9ce34" />
            <stop offset="0.5" stopColor="#ee2a7b" />
            <stop offset="1" stopColor="#6228d7" />
          </linearGradient>
        </defs>
      )}
      <g stroke={paint} strokeWidth={mono ? 1.7 : 2.1}>
        <rect x="3" y="3" width="18" height="18" rx="5.4" />
        <circle cx="12" cy="12" r="4.1" />
      </g>
      <circle cx="17.3" cy="6.7" r="1.25" fill={paint} />
    </svg>
  )
}

// Google "G" in its brand colors — used only as a recognizable link glyph.
export function GoogleIcon(props) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        fill="#4285F4"
        d="M21.6 12.23c0-.68-.06-1.34-.17-1.97H12v3.72h5.38a4.6 4.6 0 01-2 3.02v2.5h3.23c1.89-1.74 2.99-4.3 2.99-7.27z"
      />
      <path
        fill="#34A853"
        d="M12 22c2.7 0 4.96-.9 6.61-2.42l-3.23-2.5c-.9.6-2.05.96-3.38.96-2.6 0-4.8-1.76-5.59-4.12H3.08v2.59A9.99 9.99 0 0012 22z"
      />
      <path
        fill="#FBBC05"
        d="M6.41 13.92a5.99 5.99 0 010-3.84V7.49H3.08a10 10 0 000 9.02l3.33-2.59z"
      />
      <path
        fill="#EA4335"
        d="M12 5.96c1.47 0 2.79.5 3.83 1.5l2.86-2.86A9.6 9.6 0 0012 2 9.99 9.99 0 003.08 7.49l3.33 2.59C7.2 7.72 9.4 5.96 12 5.96z"
      />
    </svg>
  )
}

// Decorative botanical sprig (fine gold line leaves) used behind the hero and
// the closing section. Purely ornamental.
export function BotanicalSprig(props) {
  return (
    <svg viewBox="0 0 120 200" fill="none" aria-hidden="true" {...props}>
      <g stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 196C30 150 46 104 98 18" />
        <path d="M30 150c-16-6-24-20-22-36 16 6 24 20 22 36z" />
        <path d="M30 150c14-12 32-14 46-6-14 12-32 14-46 6z" />
        <path d="M46 110c-14-9-19-24-14-39 14 9 19 24 14 39z" />
        <path d="M46 110c16-8 34-6 46 5-16 8-34 6-46-5z" />
        <path d="M66 70c-10-11-12-26-4-39 10 11 12 26 4 39z" />
        <path d="M66 70c16-4 32 1 42 14-16 4-32-1-42-14z" />
        <path d="M84 40c-2-12 3-24 14-30 2 12-3 24-14 30z" />
      </g>
    </svg>
  )
}
