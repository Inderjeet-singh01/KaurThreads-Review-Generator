import { LightningIcon, EditIcon, GoogleIcon } from './icons.jsx'

const FEATURES = [
  { Icon: LightningIcon, tone: 'blush', lines: ['AI writes', 'a natural review'] },
  { Icon: EditIcon, tone: 'blush', lines: ['You can edit it', 'before posting'] },
  { Icon: GoogleIcon, tone: 'plain', lines: ['Post on Google', 'in one click'] },
]

export default function FeatureStrip() {
  return (
    <ul className="feature-strip" aria-label="How it works">
      {FEATURES.map(({ Icon, tone, lines }) => (
        <li className="feature" key={lines.join(' ')}>
          <span className={`feature__icon feature__icon--${tone}`} aria-hidden="true">
            <Icon className="feature__svg" />
          </span>
          <span className="feature__text">
            {lines[0]}
            <br />
            {lines[1]}
          </span>
        </li>
      ))}
    </ul>
  )
}
