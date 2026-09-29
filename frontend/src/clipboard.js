// Copies text synchronously, so the copy is finished before the "Post on
// Google" link switches to Google. Uses a hidden, read-only textarea and
// execCommand('copy'), which also works where the async Clipboard API is
// unavailable or blocked (older iOS Safari, in-app browsers, non-HTTPS).
// Returns whether the copy succeeded.
export function copyText(text) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '') // no keyboard pop-up on phones
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)

  const previousFocus = document.activeElement
  textarea.select()
  textarea.setSelectionRange(0, text.length) // iOS ignores select() alone

  let copied = false
  try {
    copied = document.execCommand('copy')
  } catch (err) {
    console.warn('Synchronous copy failed:', err)
  }

  document.body.removeChild(textarea)
  if (previousFocus instanceof HTMLElement) previousFocus.focus({ preventScroll: true })
  return copied
}
