import { ChevronRightIcon, InstagramIcon, PhoneIcon } from './icons.jsx'

const INSTAGRAM_URL = 'https://www.instagram.com/kaur_threads?stkn=dGV3NzM1ZXk5ZDI%3D'
const PHONE = '9876808614'

export default function ContactLinks() {
  return (
    <nav className="contact" aria-label="Contact Kaur Threads">
      <a
        className="contact__link"
        href={INSTAGRAM_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <span className="contact__icon contact__icon--ig" aria-hidden="true">
          <InstagramIcon className="contact__svg" />
        </span>
        <span className="contact__text">
          <span className="contact__label">Instagram</span>
          <span className="contact__value">Kaur_threads</span>
        </span>
        <ChevronRightIcon className="contact__chevron" />
      </a>

      <span className="contact__divider" aria-hidden="true" />

      <a className="contact__link" href={`tel:${PHONE}`}>
        <span className="contact__icon contact__icon--phone" aria-hidden="true">
          <PhoneIcon className="contact__svg" />
        </span>
        <span className="contact__text">
          <span className="contact__label">Call Us</span>
          <span className="contact__value">{PHONE}</span>
        </span>
        <ChevronRightIcon className="contact__chevron" />
      </a>
    </nav>
  )
}
