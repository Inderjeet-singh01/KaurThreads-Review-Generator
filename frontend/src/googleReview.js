// Builds the "Post on Google" links: the Google Maps app on the review sheet
// first, Google's "write a review" page in the browser as the backup.
//
// App: Google's official review short link (g.page/r/<id>/review) resolves to
//   https://www.google.com/maps/place//data=!4m3!3m2!1s<feature id>!12e1
// where `!12e1` opens the "rate and review" sheet in the Maps app. The feature
// id is encoded inside the place id, so that link is built from the configured
// VITE_GOOGLE_REVIEW_URL (…writereview?placeid=ChIJ…) with no extra config.
// In a browser, though, that Maps link only shows the business profile.
//
// Browser: search.google.com/local/writereview?placeid=<place id>, Google's
// documented link that opens the review box for the place. It is avoided as
// the app link: on iPhone the Google app catches it and shows the business
// panel, not the review box.
//
// Per platform:
// - Android: an intent:// link that opens the Google Maps app on the review
//   sheet. When Maps isn't installed, Chrome follows browser_fallback_url to
//   the writereview page. watchAppHandoff() backs this up for browsers that
//   ignore intent links.
// - iPhone/iPad: the https Maps link. A tapped google.com/maps link opens the
//   Google Maps app when installed, without the "cannot open page" error a
//   custom app scheme shows when the app is missing. Safari gives the page no
//   way to tell whether Maps opened (without the app the link simply loads in
//   the browser), so the guide also offers the writereview page directly.
// - Desktop: the writereview page in a new tab.

import { GOOGLE_REVIEW_URL } from './api.js'

const MAPS_PACKAGE = 'com.google.android.apps.maps'
const WRITE_REVIEW_URL = 'https://search.google.com/local/writereview?placeid='
// How long the page may stay in front after an Android intent tap before
// the Maps app is assumed missing (see watchAppHandoff).
const APP_HANDOFF_TIMEOUT_MS = 2500

// A place id (ChIJ…) is base64url of a small protobuf holding the two 64-bit
// halves of the feature id: 0a 12 | 09 <8 bytes> | 11 <8 bytes>, little-endian.
export function featureIdFromPlaceId(placeId) {
  try {
    const base64 = placeId.replace(/-/g, '+').replace(/_/g, '/')
    const binary = atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4))
    const bytes = Array.from(binary, (c) => c.charCodeAt(0))
    if (bytes.length < 20 || bytes[0] !== 0x0a || bytes[2] !== 0x09 || bytes[11] !== 0x11) {
      return null
    }
    const hex = (from) =>
      '0x' +
      (bytes
        .slice(from, from + 8)
        .reverse()
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('')
        .replace(/^0+/, '') || '0')
    return `${hex(3)}:${hex(12)}`
  } catch {
    return null
  }
}

function placeIdFromUrl(url) {
  try {
    return new URL(url).searchParams.get('placeid')
  } catch {
    return null
  }
}

function detectPlatform() {
  const ua = navigator.userAgent || ''
  if (/Android/i.test(ua)) return 'android'
  // iPadOS reports itself as a Mac; touch support tells them apart.
  if (/iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) {
    return 'ios'
  }
  return 'desktop'
}

// The Maps app link that opens the review sheet, when it can be derived from
// the place id; else the configured link as-is (e.g. a g.page review link).
export function mapsReviewUrl(configured = GOOGLE_REVIEW_URL) {
  const placeId = placeIdFromUrl(configured)
  const featureId = placeId && featureIdFromPlaceId(placeId)
  return featureId
    ? `https://www.google.com/maps/place//data=!4m3!3m2!1s${featureId}!12e1`
    : configured
}

// The browser link that opens the review box: Google's writereview page for
// the place id; else the configured link as-is. Never the Maps link, which
// only shows the business profile in a browser.
export function browserReviewUrl(configured = GOOGLE_REVIEW_URL) {
  const placeId = placeIdFromUrl(configured)
  return placeId ? WRITE_REVIEW_URL + encodeURIComponent(placeId) : configured
}

// { href, target, browserUrl, offerBrowser } for the Google links on this
// device. browserUrl is the write-review page; offerBrowser asks the guide to
// show it as its own link, where no automatic fallback is possible (iPhone).
export function googleReviewLink(configured = GOOGLE_REVIEW_URL, platform = detectPlatform()) {
  const app = mapsReviewUrl(configured)
  const browserUrl = browserReviewUrl(configured)
  if (!app) return { href: '', target: undefined, browserUrl: '', offerBrowser: false }
  if (platform === 'android') {
    const intent =
      `intent://${app.replace(/^https:\/\//, '')}#Intent;scheme=https;` +
      `package=${MAPS_PACKAGE};S.browser_fallback_url=${encodeURIComponent(browserUrl)};end`
    // No target: an intent link in a new tab can leave a blank tab behind.
    return { href: intent, target: undefined, browserUrl, offerBrowser: false }
  }
  // New tab keeps this page open to copy the review from again.
  if (platform === 'ios') {
    return { href: app, target: '_blank', browserUrl, offerBrowser: browserUrl !== app }
  }
  return { href: browserUrl, target: '_blank', browserUrl, offerBrowser: false }
}

let cancelHandoffWatch = () => {}

// Runs in the tap on an Android intent link, alongside (not instead of) the
// link's own navigation. Some browsers, mostly in-app ones, ignore intent
// links: nothing opens and browser_fallback_url is never followed. If the
// page is still in front after APP_HANDOFF_TIMEOUT_MS, open the write-review
// page. The page going to the background or losing focus (Maps opening, the
// fallback loading, a system prompt) cancels it, so it never pulls the
// customer out of the Maps app.
export function watchAppHandoff(link) {
  cancelHandoffWatch()
  if (!link.href.startsWith('intent:') || !link.browserUrl) return

  let timer
  const cancel = () => {
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', cancel)
    window.removeEventListener('pagehide', cancel)
    window.removeEventListener('blur', cancel)
  }
  document.addEventListener('visibilitychange', cancel)
  window.addEventListener('pagehide', cancel)
  window.addEventListener('blur', cancel)
  timer = setTimeout(() => {
    cancel()
    if (document.visibilityState === 'visible') window.location.href = link.browserUrl
  }, APP_HANDOFF_TIMEOUT_MS)
  cancelHandoffWatch = cancel
}
