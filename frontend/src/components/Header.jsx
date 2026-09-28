import { useEffect, useId, useState } from 'react'
import { HeartIcon } from './icons.jsx'

const NAV_ITEMS = ['Ethnic Wear', 'Suits', 'Lehengas', 'Dupattas', 'Our Story']

export default function Header() {
  const [open, setOpen] = useState(false)
  const menuId = useId()

  // Close the menu on Escape for keyboard users.
  useEffect(() => {
    if (!open) return
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <header className="site-header">
      <a className="brand" href="#top" aria-label="Kaur Threads Boutique home">
        <img className="brand__mark" src="/lotus.svg" alt="" width="36" height="28" />
        <span className="brand__text">
          <span className="brand__name">KAUR THREADS</span>
          <span className="brand__sub">BOUTIQUE</span>
        </span>
      </a>

      <div className="header__actions">
        <a className="pill pill--love" href="#top">
          <HeartIcon className="pill__icon" />
          <span>Customer Love</span>
        </a>

        <button
          type="button"
          className={`hamburger${open ? ' is-open' : ''}`}
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          aria-controls={menuId}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="hamburger__bar" />
          <span className="hamburger__bar" />
          <span className="hamburger__bar" />
        </button>
      </div>

      <nav
        id={menuId}
        className={`site-menu${open ? ' is-open' : ''}`}
        aria-label="Primary"
        hidden={!open}
      >
        <ul>
          {NAV_ITEMS.map((item) => (
            <li key={item}>
              <a href="#top" onClick={() => setOpen(false)}>
                {item}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
