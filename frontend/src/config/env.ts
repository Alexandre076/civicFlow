// VITE_* values are public and embedded in the browser bundle at build time.
export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL?.trim() || 'http://localhost:8000',
} as const
