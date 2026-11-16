// Purely a UX nicety: suppresses the auto-redirect to /app/onboarding for a
// user who explicitly chose to skip it. It is not a source of truth for
// "onboarding completed" — that is derived from whether the user has any
// Space yet (see /app and /app/onboarding), so a cleared localStorage at
// worst re-shows the wizard once, never blocks or corrupts anything.
export const ONBOARDING_SKIPPED_KEY = "noki_onboarding_skipped";
