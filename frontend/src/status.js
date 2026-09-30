// Customer-facing text for each stage of a generate request (see api.js).

// Short label for the busy Generate/Regenerate button.
export const STATUS_LABELS = {
  connecting: 'Connecting to AI service...',
  waking: 'Starting AI service...',
  generating: 'Generating your review...',
  retrying: 'Still working on it...',
}

// Longer line under the button, for the stages that take a while.
export const STATUS_HINTS = {
  waking: 'Please wait. The AI service is waking up, which can take up to a minute.',
  retrying: 'The connection was interrupted, so we are trying again.',
}

export const SUCCESS_MESSAGE = 'Review generated successfully.'

export function cooldownLabel(seconds) {
  return `Please wait ${seconds}s...`
}
