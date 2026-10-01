// Builds the "Post on Google" link so it lands on the stars + review box.
//
// Google's official review short link (g.page/r/<id>/review) resolves to
//   https://www.google.com/maps/place//data=!4m3!3m2!1s<feature id>!12e1
// where `!12e1` opens the "rate and review" sheet. The feature id is encoded
// inside the place id, so that link is built from the configured
// VITE_GOOGLE_REVIEW_URL (…writereview?placeid=ChIJ…) with no extra config.
//
// The search.google.com "writereview" link itself is avoided on phones: on
// iPhone the Google app catches it and shows the business panel, not the
// review box.
//
// Per platform:
// - Android: an intent:// link that opens the Google Maps app on the review
//   sheet. When Maps isn't installed, Chrome follows browser_fallback_url and
//   opens the same review link in the browser.
// - iPhone/iPad: the https Maps link. A tapped google.com/maps link opens the
//   Google Maps app when installed and Safari otherwise, without the "cannot
//   open page" error a custom app scheme shows when the app is missing.
// - Desktop: the https Maps link in a new tab.

import { GOOGLE_REVIEW_URL } from './api.js'

const MAPS_PACKAGE = 'com.google.android.apps.maps'

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

// The web link that opens the review box: the Maps review link when it can
// be derived from the place id, else the configured link as-is.
export function webReviewUrl(configured = GOOGLE_REVIEW_URL) {
  const placeId = placeIdFromUrl(configured)
  const featureId = placeId && featureIdFromPlaceId(placeId)
  return featureId
    ? `https://www.google.com/maps/place//data=!4m3!3m2!1s${featureId}!12e1`
    : configured
}

// { href, target } for the "Post on Google" link on this device.
export function googleReviewLink(configured = GOOGLE_REVIEW_URL, platform = detectPlatform()) {
  const web = webReviewUrl(configured)
  if (!web) return { href: '', target: undefined }
  if (platform === 'android') {
    const intent =
      `intent://${web.replace(/^https:\/\//, '')}#Intent;scheme=https;` +
      `package=${MAPS_PACKAGE};S.browser_fallback_url=${encodeURIComponent(web)};end`
    // No target: an intent link in a new tab can leave a blank tab behind.
    return { href: intent, target: undefined }
  }
  // New tab keeps this page open to copy the review from again.
  return { href: web, target: '_blank' }
}

// Opens the review link from script, after the "Review copied" guide has
// been on screen. A browser may block a scripted new tab (Safari and Firefox
// only allow one right after a tap); Google then opens in this tab instead.
export function openGoogleReview({ href, target }) {
  if (!href) return
  if (target === '_blank') {
    const tab = window.open(href, '_blank')
    if (tab) {
      tab.opener = null
      return
    }
  }
  window.location.href = href
}
