import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import ptBR from './locales/pt-BR.json'

export const supportedLocales = ['pt-BR', 'en'] as const
export type Locale = typeof supportedLocales[number]
export const localeStorageKey = 'civicflow.locale'

export function isLocale(value: unknown): value is Locale {
  return supportedLocales.some((locale) => locale === value)
}

function browserLocale(language: string): Locale | undefined {
  const base = language.toLowerCase().split('-')[0]
  if (base === 'pt') return 'pt-BR'
  if (base === 'en') return 'en'
}

export function resolveInitialLocale(): Locale {
  try {
    const saved = window.localStorage.getItem(localeStorageKey)
    if (isLocale(saved)) return saved
  } catch {
    // Storage can be disabled; browser preferences still work.
  }
  // Prefer the ordered list, then the single-language API if needed.
  const languages = [...(navigator.languages ?? []), navigator.language]
  for (const language of languages) {
    if (!language) continue
    const locale = browserLocale(language)
    if (locale) return locale
  }
  return 'pt-BR'
}

i18n.on('languageChanged', (locale) => {
  if (isLocale(locale)) document.documentElement.lang = locale
})

void i18n.use(initReactI18next).init({
  resources: { 'pt-BR': { translation: ptBR }, en: { translation: en } },
  lng: resolveInitialLocale(),
  fallbackLng: 'pt-BR',
  supportedLngs: [...supportedLocales],
  interpolation: { escapeValue: false },
  returnNull: false,
})

export async function selectLocale(locale: string): Promise<void> {
  if (!isLocale(locale)) return
  await i18n.changeLanguage(locale)
  try {
    window.localStorage.setItem(localeStorageKey, locale)
  } catch {
    // Keep the live selection even when persistence is unavailable.
  }
}

export default i18n
