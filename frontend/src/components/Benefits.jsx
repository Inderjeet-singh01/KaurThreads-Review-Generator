import { DiamondIcon, HeartIcon, PeopleIcon, StarIcon } from './icons.jsx'

const BENEFITS = [
  { Icon: DiamondIcon, lines: ['Beautiful', 'Collections'], highlight: false },
  { Icon: HeartIcon, lines: ['Quality', 'You Can Trust'], highlight: false },
  { Icon: PeopleIcon, lines: ['Warm &', 'Helpful Staff'], highlight: false },
  { Icon: StarIcon, lines: ['Loved by', 'Our Customers'], highlight: true },
]

export default function Benefits() {
  return (
    <ul className="benefits" aria-label="Why customers love Kaur Threads">
      {BENEFITS.map(({ Icon, lines, highlight }) => (
        <li className="benefit" key={lines.join(' ')}>
          <span
            className={`benefit__icon${highlight ? ' benefit__icon--highlight' : ''}`}
            aria-hidden="true"
          >
            <Icon className="benefit__svg" />
          </span>
          <span className="benefit__text">
            {lines[0]}
            <br />
            {lines[1]}
          </span>
        </li>
      ))}
    </ul>
  )
}
